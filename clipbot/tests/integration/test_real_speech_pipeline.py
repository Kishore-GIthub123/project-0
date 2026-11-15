"""REAL integration test of Whisper + Kokoro + captions + FFmpeg on a video you have the rights to.
Needs downloaded speech models (scripts/download_models.py --speech) and:
  CLIPBOT_TEST_VIDEO=<path to a clip with speech>   (Windows PowerShell: $env:CLIPBOT_TEST_VIDEO="C:\\clips\\test.mp4")
Run: python -m pytest -m integration tests/integration/test_real_speech_pipeline.py -s"""
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from clipbot import tts
from clipbot.config import Config
from clipbot.db import DB
from clipbot.transcribe import transcribe
from clipbot.worker import Worker

pytestmark = pytest.mark.integration
VIDEO = os.getenv("CLIPBOT_TEST_VIDEO")
SCRIPT = "Here is an honest take on this moment. The timing is great, and the reaction says it all."


class NoTwitch:
    def game_id(self, name):
        return None


@pytest.mark.skipif(not VIDEO, reason="set CLIPBOT_TEST_VIDEO to a local clip with speech")
def test_real_speech_pipeline(tmp_path):
    cfg = Config()
    models = cfg.data_dir / "models"
    work = tmp_path / "data"
    (work / "models").mkdir(parents=True)
    for sub in ("kokoro", "whisper"):  # reuse downloaded models
        os.symlink((models / sub).resolve(), work / "models" / sub, target_is_directory=True) if os.name != "nt" \
            else subprocess.run(["cmd", "/c", "mklink", "/J", str(work / "models" / sub), str((models / sub).resolve())], check=True)
    cfg.data_dir, cfg.activate_at, cfg.commentary_mode = work, datetime.now(timezone.utc) - timedelta(1), True
    cfg.yt_client_id = cfg.ig_user_id = ""
    db = DB(work / "clipbot.db")
    db.add_clip({"id": "it1", "broadcaster_name": "Test", "title": "Integration", "url": "local", "view_count": 0,
                 "created_at": "x"})
    w = Worker(cfg, db, NoTwitch(), download=lambda u, d, i: Path(VIDEO),
               draft_script=lambda *a: SCRIPT)  # AI is tested in test_real_ollama.py
    w.run_once()
    row = db.all()[0]
    assert row["status"] == "pending_review", row["error"]
    assert len(row["transcript"].split()) > 5, "Whisper produced no transcript"
    final = Path(row["edited_path"])
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,codec_type,duration",
                                         "-of", "json", str(final)], capture_output=True, text=True).stdout)["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next(s for s in streams if s["codec_type"] == "audio")
    assert (v["codec_name"], v["width"], v["height"]) == ("h264", 1080, 1920)
    assert abs(float(v["duration"]) - float(a["duration"])) < 0.1
    seg = json.loads(Path(row["voice_path"]).with_suffix(".json").read_text())["segments"]
    assert len(seg) == 2
    heard = transcribe(final.parent.parent / "voice" / "it1.wav", cfg.whisper_model, work / "models").lower()
    words = re.findall(r"[a-z']+", SCRIPT.lower())
    assert sum(w in heard for w in words) / len(words) > 0.8, heard
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(final), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", out)[-1])
    print(f"\nfinal {final} lufs={lufs} true_peak={peak}\ntranscript:\n{row['transcript']}")
    assert -20 < lufs < -9 and peak <= -0.5
