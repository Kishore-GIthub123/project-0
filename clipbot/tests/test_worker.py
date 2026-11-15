import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clipbot import commentary, editor
from clipbot.config import Config
from clipbot.db import DB
from clipbot.worker import Worker

CLIP = {"id": "c1", "broadcaster_name": "Streamer", "title": "Huge heist", "url": "https://clips.twitch.tv/c1",
        "view_count": 500, "created_at": "2026-11-19T10:00:00Z", "game_id": "g6"}


class FakeTwitch:
    def game_id(self, name): return "g6"
    def live_streams(self, gid): return [{"user_login": "big", "viewer_count": 9000, "title": "GTA 6 day 1"}]
    def user_ids(self, logins): return {l: "u-" + l for l in logins}
    def recent_clips(self, uid, gid, hours): return [CLIP, {**CLIP, "id": "low", "view_count": 1}]


def make_video(path: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(path)], check=True)


def cfg(tmp_path, **kw):
    c = Config()
    c.data_dir, c.allowed_broadcasters, c.min_clip_views = tmp_path, ["streamer"], 50
    c.activate_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    c.yt_client_id = c.yt_client_secret = c.yt_refresh_token = "x"
    c.ig_user_id = c.ig_access_token = "x"
    c.auto_approve = False
    c.commentary_mode = False
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def test_vertical_output(tmp_path):
    src = tmp_path / "in.mp4"
    make_video(src)
    out = editor.to_vertical(src, tmp_path / "out.mp4")
    dims = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height", "-of", "csv=p=0", str(out)],
                          capture_output=True, text=True).stdout.strip()
    assert dims == "1080,1920"


def test_waits_before_activation(tmp_path):
    c = cfg(tmp_path, activate_at=datetime.now(timezone.utc) + timedelta(days=1))
    db = DB(tmp_path / "t.db")
    Worker(c, db, FakeTwitch()).run_once()
    assert db.get_kv("status").startswith("Waiting") and db.counts() == {}


def test_full_pipeline_with_review(tmp_path):
    src = tmp_path / "src.mp4"
    make_video(src)
    db = DB(tmp_path / "t.db")
    posted = []
    w = Worker(cfg(tmp_path), db, FakeTwitch(),
               yt_upload=lambda *a: posted.append("yt") or "yt123",
               ig_upload=lambda *a: posted.append("ig") or "ig123",
               download=lambda url, d, cid: src)
    w.run_once()
    assert db.counts() == {"pending_review": 1}  # low-view clip skipped, waits for approval
    assert posted == []
    db.update("c1", status="approved")
    w.run_once()
    row = db.all()[0]
    assert row["status"] == "published" and row["yt_id"] == "yt123" and row["ig_id"] == "ig123"


def test_daily_limit_respected(tmp_path):
    src = tmp_path / "src.mp4"
    make_video(src)
    db = DB(tmp_path / "t.db")
    w = Worker(cfg(tmp_path, auto_approve=True, yt_daily_limit=0, ig_user_id=""), db, FakeTwitch(),
               yt_upload=lambda *a: "should-not-post", download=lambda url, d, cid: src)
    w.run_once()
    assert db.all()[0]["status"] == "approved" and db.all()[0]["yt_id"] is None


def make_voice(path: Path, seconds=5):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                    "-c:a", "libopus", str(path)], check=True)


def test_mix_extends_video_to_voice_length(tmp_path):
    src, voice = tmp_path / "in.mp4", tmp_path / "v.webm"
    make_video(src)  # 3s clip
    make_voice(voice, 5)  # 5s commentary
    out = commentary.mix(editor.to_vertical(src, tmp_path / "vert.mp4"), voice, tmp_path / "final.mp4")
    info = commentary.probe(out)
    assert info["audio"] and 4.8 < info["duration"] < 5.5


def test_mix_keeps_game_audio_after_voice_ends(tmp_path):
    src, voice = tmp_path / "in.mp4", tmp_path / "v.webm"
    make_video(src)  # 3s clip with audio
    make_voice(voice, 1)  # 1s commentary
    out = commentary.mix(src, voice, tmp_path / "final.mp4")
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                              "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split()
    durs = {line.split(",")[0]: float(line.split(",")[1]) for line in streams}
    assert abs(durs["audio"] - durs["video"]) < 0.1 and durs["audio"] > 2.9


def test_commentary_flow(tmp_path):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 2)
    db = DB(tmp_path / "t.db")
    posted, spoken = [], []

    def speak(text, out, models, v, speed):
        spoken.append(text)
        return voice

    w = Worker(cfg(tmp_path, commentary_mode=True, ig_user_id=""), db, FakeTwitch(),
               yt_upload=lambda cfg, path, title, desc, tags: posted.append(title) or "yt1",
               download=lambda url, d, cid: src,
               transcribe=lambda *a: "let's go chat",
               draft_script=lambda title, streamer, tr, secs, model: f"Hook! {streamer} {tr} {secs:.0f}s",
               speak=speak)
    w.run_once()
    row = db.all()[0]
    assert row["status"] == "pending_review" and posted == []
    assert row["script"] == "Hook! Streamer let's go chat 3s" and row["transcript"] == "let's go chat"
    assert row["edited_path"].endswith("final/c1.mp4") and row["vertical_path"].endswith("edited/c1.mp4")

    # edit script -> voice regenerated from the clean vertical video, not the mixed one
    db.update("c1", script="My edited take", status="script_ready")
    w.run_once()
    assert spoken[-1] == "My edited take" and db.all()[0]["status"] == "pending_review"

    db.update("c1", status="approved")
    w.run_once()
    assert db.all()[0]["status"] == "published" and posted[0].startswith("Reacting to Streamer")


def test_script_failure_marks_failed(tmp_path):
    src = tmp_path / "src.mp4"
    make_video(src)
    db = DB(tmp_path / "t.db")

    def boom(*a):
        raise RuntimeError("no key")

    Worker(cfg(tmp_path, commentary_mode=True), db, FakeTwitch(), download=lambda url, d, cid: src,
           transcribe=lambda *a: "", draft_script=boom).run_once()
    row = db.all()[0]
    assert row["status"] == "failed" and "no key" in row["error"]


def test_twitch_outage_does_not_block_pipeline(tmp_path):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 1)

    class DownTwitch(FakeTwitch):
        def live_streams(self, gid):
            raise ConnectionError("twitch down")

    db = DB(tmp_path / "t.db")
    db.add_clip(CLIP)
    db.update("c1", status="voice_ready", voice_path=str(voice), vertical_path=str(src), edited_path=str(src))
    w = Worker(cfg(tmp_path), db, DownTwitch())
    w.run_once()
    assert db.all()[0]["status"] == "pending_review"
    assert db.get_kv("status").startswith("ERROR (Twitch)")


# ---- AI provider integration in the worker (MOCKED Ollama over real HTTP)
TIMED = "[00:00] Chat look we are inside the bank right now\n[00:04] The alarm is going off go go go"


def _ollama_worker(tmp_path, fake, src, voice, transcribe=lambda *a: TIMED, **cfgkw):
    from clipbot.providers import OllamaProvider
    c = cfg(tmp_path, commentary_mode=True, ig_user_id="", **cfgkw)
    calls = {"transcribe": 0}

    def tr(*a):
        calls["transcribe"] += 1
        return transcribe(*a)

    w = Worker(c, DB(tmp_path / "t.db"), FakeTwitch(), download=lambda u, d, i: src, transcribe=tr,
               speak=lambda text, out, models, v, speed: voice,
               provider=OllamaProvider(fake.url, "qwen3:4b", retries=0))
    return w, calls


def test_worker_generates_script_with_ollama(tmp_path, fake_ollama):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 1)
    fake = fake_ollama(reply="Nobody walks into a bank this calmly. Then the alarm decides the plan for him.")
    w, calls = _ollama_worker(tmp_path, fake, src, voice, yt_client_id="")
    w.run_once()
    row = w.db.all()[0]
    assert row["status"] == "pending_review" and row["script"].startswith("Nobody walks")
    assert row["style"] == w.cfg.commentary_style and "[00:04] The alarm" in fake.requests[0]["messages"][1]["content"]
    assert "ollama/qwen3:4b" in w.db.get_kv("ai_last_success")

    # dashboard "new AI script in this style": transcript is reused, only the script is regenerated
    w.db.update("c1", style="hype", status="needs_script")
    w.run_once()
    assert calls["transcribe"] == 1 and w.db.all()[0]["style"] == "hype" and "Hype commentary" in fake.requests[-1]["messages"][1]["content"]


def test_worker_flags_insufficient_transcript_for_manual_review(tmp_path, fake_ollama):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 1)
    fake = fake_ollama()
    w, _ = _ollama_worker(tmp_path, fake, src, voice, transcribe=lambda *a: "[00:00] uh")
    w.run_once()
    row = w.db.all()[0]
    assert row["status"] == "needs_manual" and row["error"].startswith("manual:") and fake.requests == []
    # human writes the script in the dashboard -> narration + video are produced
    w.db.update("c1", script="My own words about this moment, written by hand.", status="script_ready")
    w.run_once()
    assert w.db.all()[0]["status"] == "pending_review"


def test_worker_records_ai_errors(tmp_path, fake_ollama):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 1)
    fake = fake_ollama(models=["something-else:1b"])
    w, _ = _ollama_worker(tmp_path, fake, src, voice)
    w.run_once()
    row = w.db.all()[0]
    assert row["status"] == "failed" and "ollama pull qwen3:4b" in row["error"]
    assert "ollama pull qwen3:4b" in w.db.get_kv("ai_last_error")
    assert row["script"] is None  # never falls back to a hard-coded script


def test_cleanup_removes_intermediates_after_reject(tmp_path):
    src, voice = tmp_path / "src.mp4", tmp_path / "v.webm"
    make_video(src)
    make_voice(voice, 1)
    db = DB(tmp_path / "t.db")
    w = Worker(cfg(tmp_path, commentary_mode=True), db, FakeTwitch(), download=lambda u, d, i: src,
               transcribe=lambda *a: TIMED, draft_script=lambda *a: "A written take on the moment here.",
               speak=lambda text, out, models, v, speed: voice)
    w.run_once()
    row = db.all()[0]
    vertical, final = Path(row["vertical_path"]), Path(row["edited_path"])
    assert vertical.exists() and final.exists()
    db.update("c1", status="rejected")
    w.run_once()
    row = db.all()[0]
    assert not vertical.exists() and final.exists() and row["vertical_path"] is None


def test_captions_are_burned_into_final(tmp_path):
    from clipbot import tts as T
    src = tmp_path / "src.mp4"
    make_video(src)

    class Eng:
        def create(self, text, voice, speed, lang):
            import numpy as np
            return (0.3 * np.sin(np.linspace(0, 400, 24000))).astype("float32"), 24000

    db = DB(tmp_path / "t.db")
    w = Worker(cfg(tmp_path, commentary_mode=True, watermark_text="@me"), db, FakeTwitch(),
               download=lambda u, d, i: src, transcribe=lambda *a: TIMED,
               draft_script=lambda *a: "First line here. Second line here.",
               speak=lambda text, out, models, v, speed: T.speak(text, out, models, v, speed, engine=Eng()))
    w.run_once()
    ass = (tmp_path / "captions" / "c1.ass").read_text(encoding="utf-8")
    assert "First" in ass and "@me" in ass and "Clip: Streamer on Twitch" in ass
    assert db.all()[0]["status"] == "pending_review"
