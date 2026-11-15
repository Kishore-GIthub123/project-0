"""Download and convert clips to 1080x1920 vertical video with ffmpeg."""
import subprocess
import sys
from pathlib import Path

from .commentary import H264
from .tools import FFMPEG


def download(url: str, out_dir: Path, clip_id: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{clip_id}.mp4"
    # run yt-dlp as a module so it works in a venv on Windows without the Scripts folder on PATH
    subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist", "-f", "best[ext=mp4]/best",
                    "-o", str(out), url], check=True, timeout=300)
    return out


def to_vertical(src: Path, dst: Path, max_seconds: int = 59) -> Path:
    """Blurred full-screen background + the full original frame centred (Shorts/Reels 9:16).
    The whole source frame stays visible so viewers keep the original context."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
          "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", vf,
        "-map", "[v]", "-map", "0:a?", "-t", str(max_seconds), *H264,
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(dst)],
        check=True, timeout=600)
    return dst
