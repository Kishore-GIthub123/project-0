"""Main loop: wait for launch -> find clips -> edit -> (review) -> publish."""
import functools
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ai_commentary, captions, commentary, editor, instagram, tts, youtube
from . import transcribe as stt
from .config import Config
from .db import DB, now
from .providers import ProviderConfigError, ProviderError, SecretRedactor, make_provider
from .twitch import Twitch

log = logging.getLogger("clipbot")


class Worker:
    def __init__(self, cfg: Config, db: DB, twitch: Twitch,
                 yt_upload=youtube.upload, ig_upload=instagram.upload,
                 download=editor.download, to_vertical=editor.to_vertical, mix=commentary.mix,
                 transcribe=None, draft_script=None, speak=None, provider=None):
        self.cfg, self.db, self.tw = cfg, db, twitch
        self.yt_upload, self.ig_upload = yt_upload, ig_upload
        self.download, self.to_vertical, self.mix = download, to_vertical, mix
        self.transcribe = transcribe or functools.partial(
            stt.transcribe_timed, device=cfg.whisper_device, compute_type=cfg.whisper_compute_type)
        self.speak = speak or functools.partial(
            tts.speak, pause_ms=cfg.kokoro_sentence_pause_ms,
            pronunciations=tts.load_pronunciations(cfg.pronunciation_file or None))
        # draft_script(title, streamer, transcript, seconds, style) -> script text
        self.draft_script = draft_script or self._ai_draft
        self._provider = provider
        self.game_id: str | None = None

    def provider(self):
        if self._provider is None:
            self._provider = make_provider(self.cfg)
        return self._provider

    def _ai_draft(self, title, streamer, transcript, seconds, style) -> str:
        c = self.cfg
        result = ai_commentary.write(self.provider(), title, streamer, transcript, seconds, style,
                                     c.ai_max_script_words, c.ai_max_transcript_chars, c.ai_min_transcript_words)
        return result.script

    def status(self, msg: str):
        log.info(msg)
        self.db.set_kv("status", msg)
        self.db.set_kv("heartbeat", now())

    # ---- stages ----
    def discover(self) -> int:
        live = self.tw.live_streams(self.game_id)
        self.db.set_kv("live_top", json.dumps(
            [{"user": s["user_login"], "viewers": s["viewer_count"], "title": s["title"]} for s in live]))
        added = 0
        for login, uid in self.tw.user_ids(self.cfg.allowed_broadcasters).items():
            for c in self.tw.recent_clips(uid, self.game_id, self.cfg.lookback_hours):
                if c["view_count"] >= self.cfg.min_clip_views and self.db.add_clip(c):
                    added += 1
        return added

    def process_new(self):
        raw_dir, out_dir = self.cfg.data_dir / "raw", self.cfg.data_dir / "edited"
        for c in self.db.by_status("new"):
            try:
                raw = self.download(c["url"], raw_dir, c["id"])
                edited = self.to_vertical(raw, out_dir / f"{c['id']}.mp4")
                self.db.update(c["id"], raw_path=str(raw), edited_path=str(edited), vertical_path=str(edited),
                               status="needs_script" if self.cfg.commentary_mode else self._ready())
            except Exception as e:  # noqa: BLE001
                log.exception("edit failed %s", c["id"])
                self.db.update(c["id"], status="failed", error=f"edit: {e}")

    def _ready(self) -> str:
        return "approved" if self.cfg.auto_approve else "pending_review"

    def process_scripts(self):
        models = self.cfg.data_dir / "models"
        for c in self.db.by_status("needs_script"):
            transcript = c["transcript"]
            if transcript is None:  # reuse an existing transcript when only the script is regenerated
                try:
                    transcript = self.transcribe(Path(c["raw_path"]), self.cfg.whisper_model, models)
                    self.db.update(c["id"], transcript=transcript)
                except Exception as e:  # noqa: BLE001
                    log.exception("transcribe failed %s", c["id"])
                    self.db.update(c["id"], status="failed", error=f"transcribe: {e}")
                    continue
            style = c["style"] or self.cfg.commentary_style
            try:
                seconds = commentary.probe(Path(c["vertical_path"]))["duration"]
                script = self.draft_script(c["title"], c["broadcaster"], transcript, seconds, style)
                self.db.update(c["id"], script=script, style=style, status="script_ready", error=None)
                self.db.set_kv("ai_last_success", f"{now()} · {self._ai_label()} · clip {c['id']} · {style}")
            except ai_commentary.InsufficientTranscript as e:
                # never invent commentary: a human writes it (or skips the clip) in the dashboard
                self.db.update(c["id"], style=style, status="needs_manual", error=f"manual: {e}")
            except Exception as e:  # noqa: BLE001
                log.error("script failed %s: %s", c["id"], e)
                self.db.update(c["id"], status="failed", error=f"script: {e}")
                if isinstance(e, ProviderError):
                    self.db.set_kv("ai_last_error", f"{now()} · {self._ai_label()} · {e}")

    def _ai_label(self) -> str:
        p = self._provider
        return f"{p.name}/{p.model}" if p else "custom"

    def process_tts(self):
        for c in self.db.by_status("script_ready"):
            try:
                voice = self.speak(c["script"], self.cfg.data_dir / "voice" / f"{c['id']}.wav",
                                   self.cfg.data_dir / "models", self.cfg.kokoro_voice, self.cfg.kokoro_speed)
                self.db.update(c["id"], voice_path=str(voice), status="voice_ready", error=None)
            except Exception as e:  # noqa: BLE001
                log.exception("tts failed %s", c["id"])
                self.db.update(c["id"], status="failed", error=f"tts: {e}")

    def process_voiced(self):
        for c in self.db.by_status("voice_ready"):
            try:
                video, voice = Path(c["vertical_path"] or c["edited_path"]), Path(c["voice_path"])
                subs = self._captions(c, video, voice)
                final = self.mix(video, voice, self.cfg.data_dir / "final" / f"{c['id']}.mp4", subtitles=subs,
                                 delay_ms=self.cfg.narration_delay_ms, target_lufs=self.cfg.target_lufs,
                                 game_volume=self.cfg.game_volume, duck_ratio=self.cfg.duck_ratio)
                self.db.update(c["id"], edited_path=str(final), status=self._ready(), error=None)
            except Exception as e:  # noqa: BLE001
                log.exception("mix failed %s", c["id"])
                self.db.update(c["id"], status="failed", error=f"mix: {e}")

    def _captions(self, c, video: Path, voice: Path) -> Path | None:
        sidecar = voice.with_suffix(".json")
        segments = json.loads(sidecar.read_text(encoding="utf-8"))["segments"] if sidecar.exists() else []
        duration = max(commentary.probe(video)["duration"],
                       commentary.probe(voice)["duration"] + self.cfg.narration_delay_ms / 1000)
        source = f"Clip: {c['broadcaster']} on Twitch" if self.cfg.source_label else ""
        return captions.build_ass(segments, self.cfg.data_dir / "captions" / f"{c['id']}.ass", min(duration, 59),
                                  captions.CaptionStyle.from_config(self.cfg), self.cfg.narration_delay_ms / 1000,
                                  self.cfg.watermark_text, source)

    def cleanup(self):
        """Delete intermediate files of finished clips (published/rejected); the final MP4 is kept."""
        if self.cfg.keep_intermediate_files:
            return
        for status in ("published", "rejected"):
            for c in self.db.by_status(status):
                paths = [c["raw_path"], c["vertical_path"], c["voice_path"]]
                if not any(paths):
                    continue
                extra = [str(Path(c["voice_path"]).with_suffix(".json"))] if c["voice_path"] else []
                extra.append(str(self.cfg.data_dir / "captions" / f"{c['id']}.ass"))
                for p in [*paths, *extra]:
                    if p and p != c["edited_path"]:
                        Path(p).unlink(missing_ok=True)
                self.db.update(c["id"], raw_path=None, vertical_path=None, voice_path=None)

    def publish(self):
        for c in self.db.by_status("approved"):
            if c["voice_path"]:
                title = f"Reacting to {c['broadcaster']}: {c['title']} #GTA6 #Shorts"
                credit = (f"My commentary on a moment from {c['broadcaster']}'s stream.\n"
                          f"Original: {c['url']}")
            else:
                title = f"{c['title']} | {c['broadcaster']} #GTA6 #Shorts"
                credit = f"Clip: {c['broadcaster']} on Twitch - {c['url']}\nPosted with the streamer's permission."
            path = Path(c["edited_path"])
            try:
                if (self.cfg.youtube_enabled and not c["yt_id"]
                        and self.db.posted_last_24h("yt_id") < self.cfg.yt_daily_limit):
                    self.db.update(c["id"], yt_id=self.yt_upload(
                        self.cfg, path, title, credit, ["GTA 6", "GTA VI", c["broadcaster"]]))
                if (self.cfg.instagram_enabled and not c["ig_id"]
                        and self.db.posted_last_24h("ig_id") < self.cfg.ig_daily_limit):
                    self.db.update(c["id"], ig_id=self.ig_upload(
                        self.cfg, path, f"{c['title']}\n\n{credit}\n#gta6 #gtavi #gaming"))
            except Exception as e:  # noqa: BLE001
                log.exception("publish failed %s", c["id"])
                self.db.update(c["id"], status="failed", error=f"publish: {e}")
                continue
            row = self.db.conn.execute("SELECT yt_id, ig_id FROM clips WHERE id=?", (c["id"],)).fetchone()
            done = ((not self.cfg.youtube_enabled or row["yt_id"])
                    and (not self.cfg.instagram_enabled or row["ig_id"])
                    and (self.cfg.youtube_enabled or self.cfg.instagram_enabled))
            if done:
                self.db.update(c["id"], status="published", error=None)

    # ---- loop ----
    def run_once(self):
        if datetime.now(timezone.utc) < self.cfg.activate_at:
            self.status(f"Waiting for activation at {self.cfg.activate_at.isoformat()}")
            return
        # Twitch problems must not block clips that are already in the pipeline
        added, note = 0, ""
        try:
            if not self.game_id:
                self.game_id = self.tw.game_id(self.cfg.game_name)
            if not self.game_id:
                note = f"'{self.cfg.game_name}' not found on Twitch yet"
            elif not self.cfg.allowed_broadcasters:
                note = "ALLOWED_BROADCASTERS is empty - add streamers who gave permission"
            else:
                added = self.discover()
        except Exception as e:  # noqa: BLE001
            log.exception("twitch discovery failed")
            note = f"ERROR (Twitch): {e}"
        self.process_new()
        self.process_scripts()
        self.process_tts()
        self.process_voiced()
        self.publish()
        self.cleanup()
        self.status(note or f"Active: {added} new clips this run")

    def run_forever(self):
        while True:
            try:
                self.run_once()
            except Exception as e:  # noqa: BLE001
                log.exception("run failed")
                self.status(f"ERROR: {e}")
            time.sleep(self.cfg.poll_seconds)


def setup_logging(cfg: Config):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    redact = SecretRedactor([cfg.anthropic_api_key, cfg.twitch_client_secret, cfg.yt_client_secret,
                             cfg.yt_refresh_token, cfg.ig_access_token, cfg.dashboard_password])
    for h in logging.getLogger().handlers:
        h.addFilter(redact)


def main():
    cfg = Config()
    setup_logging(cfg)
    db = DB(cfg.data_dir / "clipbot.db")
    provider = None
    if cfg.commentary_mode:
        try:
            provider = make_provider(cfg)  # validates configuration; never needs a key for Ollama
        except ProviderConfigError as e:
            log.error("AI configuration error: %s", e)
            sys.exit(2)
        h = provider.health()
        log.info("AI provider %s, model %s: %s", h.provider, h.model, h.detail)
        if not (h.reachable and h.model_available):
            db.set_kv("ai_last_error", f"{now()} · {provider.name}/{provider.model} · startup check: {h.detail}")
    Worker(cfg, db, Twitch(cfg.twitch_client_id, cfg.twitch_client_secret), provider=provider).run_forever()


if __name__ == "__main__":
    main()
