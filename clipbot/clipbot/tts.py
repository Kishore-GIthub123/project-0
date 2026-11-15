"""Kokoro text-to-speech (Apache-2.0): https://huggingface.co/hexgrad/Kokoro-82M"""
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

HF = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
_engine = {}


def _fetch(url: str, dst: Path):
    if dst.exists() and dst.stat().st_size > 0:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dst.with_suffix(dst.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.rename(dst)


def _load(models_dir: Path, voice: str):
    key = (str(models_dir), voice)
    if key not in _engine:
        from kokoro_onnx import Kokoro
        d = models_dir / "kokoro"
        _fetch(f"{HF}/onnx/model_quantized.onnx", d / "model.onnx")
        _fetch(f"{HF}/voices/{voice}.bin", d / f"{voice}.bin")
        npz = d / f"{voice}.npz"
        if not npz.exists():
            np.savez(npz, **{voice: np.fromfile(d / f"{voice}.bin", dtype=np.float32).reshape(-1, 1, 256)})
        _engine[key] = Kokoro(str(d / "model.onnx"), str(npz))
    return _engine[key]


def speak(text: str, out: Path, models_dir: Path, voice: str = "am_michael", speed: float = 1.05) -> Path:
    lang = "en-gb" if voice.startswith("b") else "en-us"
    audio, sr = _load(models_dir, voice).create(text, voice=voice, speed=speed, lang=lang)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, audio, sr)
    return out
