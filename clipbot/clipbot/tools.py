"""Locate external tools (ffmpeg/ffprobe). Works on Windows and Linux via PATH or explicit env vars."""
import os
import shutil
import subprocess

FFMPEG = os.getenv("FFMPEG_BIN") or "ffmpeg"
FFPROBE = os.getenv("FFPROBE_BIN") or "ffprobe"


def find(binary: str) -> str | None:
    """Full path of an executable, or None (shutil.which also resolves .exe on Windows)."""
    return binary if os.path.isfile(binary) else shutil.which(binary)


def ffmpeg_info() -> dict:
    out = {"ffmpeg": find(FFMPEG), "ffprobe": find(FFPROBE), "version": None, "libass": False, "libx264": False}
    if out["ffmpeg"]:
        v = subprocess.run([FFMPEG, "-hide_banner", "-version"], capture_output=True, text=True, timeout=30)
        out["version"] = (v.stdout.splitlines() or [""])[0]
        f = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30).stdout
        out["libass"] = " subtitles " in f
        e = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
        out["libx264"] = "libx264" in e
    return out
