"""REAL integration test: talks to your local Ollama and the configured model (no mocks).
Run on the Windows PC:  .venv\\Scripts\\python -m pytest -m integration tests/integration -s"""
import time

import pytest

from clipbot import ai_commentary
from clipbot.config import Config
from clipbot.providers import OllamaProvider, make_provider

pytestmark = pytest.mark.integration

TRANSCRIPT = """[00:00] Chat, chat, look, we're actually inside the bank right now.
[00:04] Okay the alarm is going off, the alarm is going off, go go go!
[00:09] Wait, why is the getaway car on fire? Who did that? Was that me?
[00:14] Bro the cops are already here, I'm taking the boat, I'm taking the boat!
[00:21] I can't drive a boat. We're stuck on the sand!
[00:27] Chat, we made it out with like twelve dollars."""


@pytest.fixture(scope="module")
def provider():
    cfg = Config()
    if cfg.ai_provider != "ollama":
        pytest.skip("AI_PROVIDER is not ollama")
    p = make_provider(cfg)
    h = p.health()
    if not h.reachable:
        pytest.fail(f"Ollama not reachable: {h.detail}")
    if not h.model_available:
        pytest.fail(f"model missing: {h.detail}")
    return p


def test_ollama_health(provider: OllamaProvider):
    assert provider.version()
    assert provider.has_model(provider.list_models())


@pytest.mark.parametrize("style", list(ai_commentary.STYLES))
def test_real_commentary(provider, style):
    t0 = time.time()
    c = ai_commentary.write(provider, "Bank heist goes wrong", "TestStreamer", TRANSCRIPT, 30, style)
    took = time.time() - t0
    print(f"\n[{style}] {took:.1f}s attempts={c.attempts}\n{c.script}")
    assert 8 <= len(c.script.split()) <= c.word_limit
    assert "<think>" not in c.script
    assert not ai_commentary.problems(c.script, TRANSCRIPT), ai_commentary.problems(c.script, TRANSCRIPT)
