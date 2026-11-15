"""Environment check (cross-platform). Run: python -m clipbot.check_env   (exit code 0 = ready)."""
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config
from .providers import ProviderConfigError, make_provider
from .tools import ffmpeg_info

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def _ram_gb():
    try:
        if sys.platform == "win32":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30, m.ullAvailPhys / 2**30
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
        avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES") / 2**30
        return total, avail
    except (OSError, ValueError, AttributeError):
        return None, None


def _gpu():
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    r = subprocess.run([smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=20)
    return [dict(zip(("name", "vram_mb", "driver"), [x.strip() for x in line.split(",")]))
            for line in r.stdout.splitlines() if line.strip()] if r.returncode == 0 else None


def run(cfg: Config | None = None) -> list[tuple[str, str, str]]:
    cfg = cfg or Config()
    res = []
    add = lambda status, name, detail: res.append((status, name, detail))  # noqa: E731

    v = sys.version_info
    add(OK if v >= (3, 11) else FAIL, "Python", f"{platform.python_version()} ({sys.executable})")

    f = ffmpeg_info()
    if not f["ffmpeg"] or not f["ffprobe"]:
        add(FAIL, "FFmpeg", "ffmpeg/ffprobe not found on PATH (set FFMPEG_BIN / FFPROBE_BIN or install FFmpeg)")
    else:
        add(OK if f["libass"] and f["libx264"] else FAIL, "FFmpeg",
            f"{f['version']} · libx264={f['libx264']} · libass(captions)={f['libass']}")

    try:
        p = make_provider(cfg)
        h = p.health(timeout=5)
        if not h.reachable:
            add(FAIL, f"AI provider ({p.name})", h.detail)
        else:
            add(OK if h.model_available else FAIL, f"AI provider ({p.name})",
                f"model {p.model}: {h.detail}" + (f" · Ollama {h.version}" if h.version else ""))
            if h.local_models:
                add(OK, "Local models", ", ".join(h.local_models))
    except ProviderConfigError as e:
        add(FAIL, "AI configuration", str(e))

    kdir = cfg.data_dir / "models" / "kokoro"
    have_k = (kdir / "model.onnx").exists() and (kdir / f"{cfg.kokoro_voice}.bin").exists()
    add(OK if have_k else WARN, "Kokoro voice", f"{cfg.kokoro_voice} " + ("downloaded" if have_k else
        "missing - run: python scripts/download_models.py --speech"))
    wdir = cfg.data_dir / "models" / "whisper"
    have_w = wdir.exists() and any(wdir.iterdir())
    add(OK if have_w else WARN, "Whisper model", f"{cfg.whisper_model} " + ("downloaded" if have_w else
        "missing - run: python scripts/download_models.py --speech"))

    total, avail = _ram_gb()
    if total:
        add(OK if total >= 16 else WARN, "RAM", f"{total:.1f} GB total, {avail:.1f} GB free")
    gpus = _gpu()
    add(OK if gpus else WARN, "NVIDIA GPU", json.dumps(gpus) if gpus else
        "nvidia-smi not found - CPU inference will be used (that is fine)")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(cfg.data_dir).free / 2**30
    add(OK if free >= 15 else WARN, "Disk", f"{free:.1f} GB free at {Path(cfg.data_dir).resolve()}")
    return res


def main():
    res = run()
    for status, name, detail in res:
        print(f"[{status:4}] {name}: {detail}")
    sys.exit(1 if any(s == FAIL for s, _, _ in res) else 0)


if __name__ == "__main__":
    main()
