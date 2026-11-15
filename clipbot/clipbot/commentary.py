"""Mix your recorded commentary over a clip: clean the voice, duck game audio under it."""
import json
import subprocess
from pathlib import Path

# highpass/lowpass: remove rumble & hiss; afftdn: noise reduction; compressor + loudnorm: even, broadcast loudness
VOICE_CHAIN = ("highpass=f=80,lowpass=f=12000,afftdn=nf=-25,"
               "acompressor=threshold=-20dB:ratio=3:attack=5:release=100,loudnorm=I=-14:TP=-1.5:LRA=11")


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return {"duration": float(j["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in j.get("streams", []))}


def mix(video: Path, voice: Path, out: Path, max_seconds: int = 59) -> Path:
    v, a = probe(video), probe(voice)
    hold = max(0.0, a["duration"] - v["duration"])  # freeze last frame if you talk longer than the clip
    vf = f"[0:v]tpad=stop_mode=clone:stop_duration={hold:.2f}[v]"
    if v["audio"]:
        af = (f"[1:a]{VOICE_CHAIN},asplit=2[vsc][vmix];[0:a]volume=0.8[game];"
              "[game][vsc]sidechaincompress=threshold=0.02:ratio=10:attack=20:release=400[duck];"
              "[duck][vmix]amix=inputs=2:duration=longest:normalize=0[a]")
    else:
        af = f"[1:a]{VOICE_CHAIN}[a]"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(voice),
        "-filter_complex", f"{vf};{af}", "-map", "[v]", "-map", "[a]", "-t", str(max_seconds),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart", str(out)], check=True, timeout=600)
    return out
