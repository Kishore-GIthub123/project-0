"""Main loop: wait for launch -> find clips -> edit -> (review) -> publish."""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import editor, instagram, youtube
from .config import Config
from .db import DB, now
from .twitch import Twitch

log = logging.getLogger("clipbot")


class Worker:
    def __init__(self, cfg: Config, db: DB, twitch: Twitch,
                 yt_upload=youtube.upload, ig_upload=instagram.upload,
                 download=editor.download, to_vertical=editor.to_vertical):
        self.cfg, self.db, self.tw = cfg, db, twitch
        self.yt_upload, self.ig_upload = yt_upload, ig_upload
        self.download, self.to_vertical = download, to_vertical
        self.game_id: str | None = None

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
                self.db.update(c["id"], raw_path=str(raw), edited_path=str(edited),
                               status="approved" if self.cfg.auto_approve else "pending_review")
            except Exception as e:  # noqa: BLE001
                log.exception("edit failed %s", c["id"])
                self.db.update(c["id"], status="failed", error=f"edit: {e}")

    def publish(self):
        for c in self.db.by_status("approved"):
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
        if not self.game_id:
            self.game_id = self.tw.game_id(self.cfg.game_name)
            if not self.game_id:
                self.status(f"'{self.cfg.game_name}' not found on Twitch yet")
                return
        if not self.cfg.allowed_broadcasters:
            self.status("ALLOWED_BROADCASTERS is empty - add streamers who gave permission")
            return
        added = self.discover()
        self.process_new()
        self.publish()
        self.status(f"Active: {added} new clips this run")

    def run_forever(self):
        while True:
            try:
                self.run_once()
            except Exception as e:  # noqa: BLE001
                log.exception("run failed")
                self.status(f"ERROR: {e}")
            time.sleep(self.cfg.poll_seconds)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config()
    Worker(cfg, DB(cfg.data_dir / "clipbot.db"),
           Twitch(cfg.twitch_client_id, cfg.twitch_client_secret)).run_forever()


if __name__ == "__main__":
    main()
