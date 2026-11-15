import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from clipbot import editor
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
