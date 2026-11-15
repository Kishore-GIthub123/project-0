"""Kokoro text-to-speech (Apache-2.0): https://huggingface.co/hexgrad/Kokoro-82M"""
import json
import os
import re
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

HF = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main"
DEFAULT_PRONUNCIATIONS = Path(__file__).with_name("pronunciations.json")
_engine = {}


class ModelMissing(RuntimeError):
    pass


def auto_download() -> bool:
    return os.getenv("AUTO_DOWNLOAD_SPEECH_MODELS", "false").lower() == "true"


def _fetch(url: str, dst: Path, allow_download: bool):
    if dst.exists() and dst.stat().st_size > 0:
        return
    if not allow_download:
        raise ModelMissing(f"{dst} is missing - run: python scripts/download_models.py --speech")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dst.with_suffix(dst.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        tmp.replace(dst)  # replace() also overwrites on Windows


def ensure_models(models_dir: Path, voice: str, allow_download: bool | None = None) -> tuple[Path, Path]:
    allow = auto_download() if allow_download is None else allow_download
    d = models_dir / "kokoro"
    _fetch(f"{HF}/onnx/model_quantized.onnx", d / "model.onnx", allow)
    _fetch(f"{HF}/voices/{voice}.bin", d / f"{voice}.bin", allow)
    npz = d / f"{voice}.npz"
    if not npz.exists():
        np.savez(npz, **{voice: np.fromfile(d / f"{voice}.bin", dtype=np.float32).reshape(-1, 1, 256)})
    return d / "model.onnx", npz


def _load(models_dir: Path, voice: str):
    key = (str(models_dir), voice)
    if key not in _engine:
        from kokoro_onnx import Kokoro
        model, npz = ensure_models(models_dir, voice)
        _engine[key] = Kokoro(str(model), str(npz))
    return _engine[key]


def load_pronunciations(path: str | Path | None = None) -> dict[str, str]:
    p = Path(path) if path else DEFAULT_PRONUNCIATIONS
    if not p.exists():
        return {}
    return {k: v for k, v in json.loads(p.read_text(encoding="utf-8")).items() if not k.startswith("_")}


def apply_pronunciations(text: str, mapping: dict[str, str]) -> str:
    for word in sorted(mapping, key=len, reverse=True):
        text = re.sub(rf"(?<![\w']){re.escape(word)}(?![\w'])", mapping[word], text)
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text.strip()))
    return [p for p in parts if re.search(r"\w", p)]


def trim_silence(audio: np.ndarray, sr: int, threshold_db: float = -45, pad_ms: int = 40) -> np.ndarray:
    if audio.size == 0:
        return audio
    level = 10 ** (threshold_db / 20)
    loud = np.flatnonzero(np.abs(audio) > level)
    if loud.size == 0:
        return audio[:0]
    pad = int(sr * pad_ms / 1000)
    return audio[max(0, loud[0] - pad): min(audio.size, loud[-1] + pad + 1)]


def speak(text: str, out: Path, models_dir: Path, voice: str = "am_michael", speed: float = 1.05,
          pause_ms: int = 180, pronunciations: dict | None = None, engine=None) -> Path:
    """Synthesise `text` sentence by sentence. Writes `out` (wav) and `out`.json with per-sentence timings
    (used for captions). Captions keep the original wording; only the spoken text gets respellings."""
    eng = engine or _load(models_dir, voice)
    lang = "en-gb" if voice.startswith("b") else "en-us"
    mapping = load_pronunciations() if pronunciations is None else pronunciations
    chunks, segments, t, sr = [], [], 0.0, 24000
    for sentence in split_sentences(text):
        audio, sr = eng.create(apply_pronunciations(sentence, mapping), voice=voice, speed=speed, lang=lang)
        audio = trim_silence(np.asarray(audio, dtype=np.float32), sr)
        if audio.size == 0:
            continue
        if chunks:
            gap = np.zeros(int(sr * pause_ms / 1000), dtype=np.float32)
            chunks.append(gap)
            t += gap.size / sr
        segments.append({"text": sentence, "start": round(t, 3), "end": round(t + audio.size / sr, 3)})
        chunks.append(audio)
        t += audio.size / sr
    if not chunks:
        raise RuntimeError("TTS produced no audio (empty script?)")
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, np.concatenate(chunks), sr)
    out.with_suffix(".json").write_text(json.dumps({"voice": voice, "segments": segments}, indent=1), encoding="utf-8")
    return out
