"""Mix commentary over a clip: clean the voice, duck game audio under it, burn in captions."""
import json
import subprocess
from pathlib import Path

from .tools import FFMPEG, FFPROBE

# highpass/lowpass: remove rumble & hiss; afftdn: light noise reduction; compressor + loudnorm: even loudness
VOICE_CHAIN = ("highpass=f=80,lowpass=f=12000,afftdn=nf=-25,"
               "acompressor=threshold=-20dB:ratio=3:attack=5:release=100,loudnorm=I={lufs}:TP=-1.5:LRA=11")
LIMITER = "alimiter=limit=0.891:level=disabled"  # -1 dBFS ceiling on the final mix

H264 = ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", "30", "-preset", "veryfast", "-crf", "21"]


def probe(path: Path) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return {"duration": float(j["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in j.get("streams", []))}


def mix(video: Path, voice: Path, out: Path, max_seconds: int = 59, subtitles: Path | None = None,
        delay_ms: int = 0, target_lufs: float = -14.0, game_volume: float = 0.8, duck_ratio: float = 10.0) -> Path:
    video, voice, out = Path(video).resolve(), Path(voice).resolve(), Path(out).resolve()
    v, a = probe(video), probe(voice)
    delay = max(0, delay_ms) / 1000
    narration_end = a["duration"] + delay
    hold = max(0.0, narration_end - v["duration"])  # freeze the last frame if the narration is longer than the clip
    total = min(max(v["duration"], narration_end), max_seconds)
    vf = f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.2f}"
    if subtitles:
        vf += f",subtitles=filename='{Path(subtitles).name}'"
    vf += "[v]"
    voice_chain = VOICE_CHAIN.format(lufs=target_lufs) + (f",adelay=delays={int(delay_ms)}:all=1" if delay_ms else "")
    # apad keeps both tracks running so neither the ducker nor the mixer stops when the voice ends;
    # atrim cuts the audio to exactly the video length
    if v["audio"]:
        af = (f"[1:a]{voice_chain},apad,asplit=2[vsc][vmix];[0:a]volume={game_volume},apad[game];"
              f"[game][vsc]sidechaincompress=threshold=0.02:ratio={duck_ratio}:attack=20:release=400[duck];"
              f"[duck][vmix]amix=inputs=2:duration=first:normalize=0,{LIMITER},atrim=0:{total:.3f}[a]")
    else:
        af = f"[1:a]{voice_chain},apad,{LIMITER},atrim=0:{total:.3f}[a]"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice),
        "-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", *H264,
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out)],
        check=True, timeout=900, cwd=str(Path(subtitles).resolve().parent) if subtitles else None)
    return out
