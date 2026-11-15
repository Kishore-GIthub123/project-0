"""Local speech-to-text with faster-whisper (MIT): https://github.com/SYSTRAN/faster-whisper"""
import subprocess
from pathlib import Path

import numpy as np

from .tools import FFMPEG

_model = {}


def _pcm16k(path: Path) -> np.ndarray:
    # decode with ffmpeg (avoids PyAV version issues): mono, 16 kHz, float32
    raw = subprocess.run([FFMPEG, "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=300).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _segments(path: Path, model_name: str, models_dir: Path | None, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    key = (model_name, device, compute_type)
    if key not in _model:
        from .tts import auto_download
        try:
            _model[key] = WhisperModel(model_name, device=device, compute_type=compute_type,
                                       download_root=str(models_dir / "whisper") if models_dir else None,
                                       local_files_only=not auto_download())
        except Exception as e:  # noqa: BLE001
            if not auto_download():
                raise RuntimeError(f"Whisper model '{model_name}' not available locally ({e}) - "
                                   "run: python scripts/download_models.py --speech") from e
            raise
    audio = _pcm16k(path)
    if audio.size == 0:
        return []
    segments, _ = _model[key].transcribe(audio, vad_filter=True)
    return [(s.start, s.text.strip()) for s in segments if s.text.strip()]


def transcribe(path: Path, model_name: str = "base.en", models_dir: Path | None = None,
               device: str = "cpu", compute_type: str = "int8") -> str:
    """Plain text transcript (kept for compatibility)."""
    return " ".join(t for _, t in _segments(path, model_name, models_dir, device, compute_type))[:4000]


def transcribe_timed(path: Path, model_name: str = "base.en", models_dir: Path | None = None,
                     device: str = "cpu", compute_type: str = "int8") -> str:
    """One line per speech segment: '[mm:ss] text' - gives the AI the order of events."""
    lines = [f"[{int(s // 60):02d}:{int(s % 60):02d}] {t}"
             for s, t in _segments(path, model_name, models_dir, device, compute_type)]
    return "\n".join(lines)
