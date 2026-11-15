"""Explicitly download models. Nothing is downloaded unless you run this.

  python scripts/download_models.py --speech    # Kokoro voice (~90 MB) + Whisper (~150 MB)
  python scripts/download_models.py --ollama    # pull OLLAMA_MODEL through the local Ollama service
  python scripts/download_models.py --list      # list models installed in Ollama
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipbot import tts  # noqa: E402
from clipbot.config import Config  # noqa: E402
from clipbot.providers import OllamaProvider, ProviderError, make_provider  # noqa: E402


def speech(cfg: Config):
    print(f"Kokoro voice '{cfg.kokoro_voice}' -> {cfg.data_dir / 'models' / 'kokoro'}")
    tts.ensure_models(cfg.data_dir / "models", cfg.kokoro_voice, allow_download=True)
    print(f"Whisper '{cfg.whisper_model}' -> {cfg.data_dir / 'models' / 'whisper'}")
    from faster_whisper import WhisperModel
    WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8",
                 download_root=str(cfg.data_dir / "models" / "whisper"))
    print("speech models ready")


def ollama_provider(cfg: Config) -> OllamaProvider:
    cfg.ai_provider = "ollama"
    return make_provider(cfg)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speech", action="store_true")
    ap.add_argument("--ollama", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", help="override OLLAMA_MODEL for --ollama")
    a = ap.parse_args()
    if not (a.speech or a.ollama or a.list):
        ap.print_help()
        return 1
    cfg = Config()
    if a.model:
        cfg.ollama_model = a.model
    try:
        if a.list:
            p = ollama_provider(cfg)
            print(f"Ollama {p.version()} at {p.base_url}")
            for m in p.list_models():
                print(" -", m)
        if a.ollama:
            p = ollama_provider(cfg)
            print(f"Pulling {p.model} from the Ollama library (this can be several GB)...")
            last = {}

            def progress(msg):
                if msg.get("total") and msg.get("completed") is not None:
                    pct = 100 * msg["completed"] / msg["total"]
                    if int(pct) != last.get("pct"):
                        last["pct"] = int(pct)
                        print(f"\r{msg.get('status', '')[:40]:40} {pct:5.1f}%", end="", flush=True)
                elif msg.get("status") != last.get("status"):
                    last["status"] = msg.get("status")
                    print(f"\n{msg.get('status')}", end="", flush=True)

            p.pull(progress)
            print(f"\n{p.model} is installed: {p.has_model(p.list_models())}")
        if a.speech:
            speech(cfg)
    except ProviderError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
