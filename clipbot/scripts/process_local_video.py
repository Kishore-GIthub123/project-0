"""Run the full pipeline on a local video you have the rights to (no Twitch needed):
transcribe -> AI script -> Kokoro narration -> captions -> mix. The clip then appears in the dashboard for review.

  python scripts/process_local_video.py path\\to\\clip.mp4 --style funny --streamer "My Friend"
"""
import argparse
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipbot.config import Config  # noqa: E402
from clipbot.db import DB  # noqa: E402
from clipbot.worker import Worker, setup_logging  # noqa: E402


class NoTwitch:
    def game_id(self, name): return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--title", default=None)
    ap.add_argument("--streamer", default="Local")
    ap.add_argument("--style", default=None)
    a = ap.parse_args()
    src = Path(a.video).resolve()
    if not src.exists():
        print(f"not found: {src}")
        return 1
    cfg = Config()
    cfg.activate_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    cfg.commentary_mode, cfg.auto_approve = True, False   # always manual approval
    cfg.yt_client_id = cfg.ig_user_id = ""                  # never publish from this script
    setup_logging(cfg)
    db = DB(cfg.data_dir / "clipbot.db")
    cid = "local-" + hashlib.sha1(str(src).encode()).hexdigest()[:10]
    db.add_clip({"id": cid, "broadcaster_name": a.streamer, "title": a.title or src.stem,
                 "url": src.as_uri(), "view_count": 0, "created_at": datetime.now(timezone.utc).isoformat()})
    db.update(cid, status="new", style=a.style, error=None)
    w = Worker(cfg, db, NoTwitch(), download=lambda url, out_dir, clip_id: src)
    w.run_once()
    row = db.conn.execute("SELECT status, error, edited_path, script FROM clips WHERE id=?", (cid,)).fetchone()
    print(f"\nclip {cid}: status={row['status']} error={row['error']}")
    print(f"script: {row['script']}")
    print(f"final video: {row['edited_path']}")
    return 0 if row["status"] in ("pending_review", "needs_manual") else 2


if __name__ == "__main__":
    sys.exit(main())
