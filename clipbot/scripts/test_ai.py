"""REAL integration test of the configured AI provider (no mocks). Uses your local Ollama (or Anthropic).

  python scripts/test_ai.py                       # health + one script per style from a sample transcript
  python scripts/test_ai.py --style funny --transcript-file my_transcript.txt --seconds 30
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipbot import ai_commentary  # noqa: E402
from clipbot.config import Config  # noqa: E402
from clipbot.providers import ProviderError, make_provider  # noqa: E402

SAMPLE = """[00:00] Chat, chat, look, we're actually inside the bank right now.
[00:04] Okay the alarm is going off, the alarm is going off, go go go!
[00:09] Wait, why is the getaway car on fire? Who did that? Was that me?
[00:14] Bro the cops are already here, I'm taking the boat, I'm taking the boat!
[00:21] I can't drive a boat. I can't drive a boat! We're stuck on the sand!
[00:27] Chat, we made it out with like twelve dollars. Twelve dollars."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=list(ai_commentary.STYLES), action="append")
    ap.add_argument("--transcript-file")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--title", default="Bank heist goes wrong")
    ap.add_argument("--streamer", default="TestStreamer")
    a = ap.parse_args()
    cfg = Config()
    transcript = Path(a.transcript_file).read_text(encoding="utf-8") if a.transcript_file else SAMPLE
    try:
        p = make_provider(cfg)
    except ProviderError as e:
        print(f"CONFIG ERROR: {e}")
        return 2
    h = p.health()
    print(f"provider={h.provider} model={h.model} reachable={h.reachable} model_available={h.model_available}")
    print(f"detail: {h.detail}")
    if not (h.reachable and h.model_available):
        return 3
    rc = 0
    for style in a.style or list(ai_commentary.STYLES):
        t0 = time.time()
        try:
            c = ai_commentary.write(p, a.title, a.streamer, transcript, a.seconds, style, cfg.ai_max_script_words,
                                    cfg.ai_max_transcript_chars, cfg.ai_min_transcript_words)
            print(f"\n=== {style} ({time.time() - t0:.1f}s, {len(c.script.split())}/{c.word_limit} words, "
                  f"attempts={c.attempts}) ===\n{c.script}")
            left = ai_commentary.problems(c.script, transcript)
            if left:
                print(f"WARNING still has issues: {left}")
        except ProviderError as e:
            print(f"\n=== {style} FAILED after {time.time() - t0:.1f}s: {e}")
            rc = 4
    return rc


if __name__ == "__main__":
    sys.exit(main())
