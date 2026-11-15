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
