"""Download and convert clips to 1080x1920 vertical video with ffmpeg."""
import subprocess
from pathlib import Path


def download(url: str, out_dir: Path, clip_id: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{clip_id}.mp4"
    subprocess.run(["yt-dlp", "-q", "--no-playlist", "-f", "best[ext=mp4]/best", "-o", str(out), url],
                   check=True, timeout=300)
    return out


def to_vertical(src: Path, dst: Path, max_seconds: int = 59) -> Path:
    """Blurred full-screen background + original video centred (Shorts/Reels 9:16)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
          "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", vf,
        "-map", "[v]", "-map", "0:a?", "-t", str(max_seconds), "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(dst)],
        check=True, timeout=600)
    return dst
