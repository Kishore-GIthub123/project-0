"""Local speech-to-text with faster-whisper (MIT): https://github.com/SYSTRAN/faster-whisper"""
import subprocess
from pathlib import Path

import numpy as np

_model = {}


def _pcm16k(path: Path) -> np.ndarray:
    # decode with ffmpeg (avoids PyAV version issues): mono, 16 kHz, float32
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=300).stdout
    return np.frombuffer(raw, dtype=np.float32)


def transcribe(path: Path, model_name: str = "base.en", models_dir: Path | None = None) -> str:
    from faster_whisper import WhisperModel
    if model_name not in _model:
        _model[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8",
                                          download_root=str(models_dir / "whisper") if models_dir else None)
    audio = _pcm16k(path)
    if audio.size == 0:
        return ""
    segments, _ = _model[model_name].transcribe(audio, vad_filter=True)
    return " ".join(s.text.strip() for s in segments)[:4000]
