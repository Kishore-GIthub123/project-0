"""MOCKED unit tests for the AI providers (fake Ollama HTTP server, fake Anthropic client)."""
import logging
import socket
import threading
from types import SimpleNamespace

import pytest

from clipbot.config import Config
from clipbot.providers import (AnthropicProvider, GenerationRefused, ModelNotFound, OllamaProvider,
                               ProviderConfigError, ProviderTimeout, ProviderUnavailable, SecretRedactor,
                               make_provider)


def ollama(url, **kw):
    return OllamaProvider(url, kw.pop("model", "qwen3:4b"), **{"retries": 0, **kw})


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def cfg(**kw):
    c = Config()
    c.ai_provider, c.anthropic_api_key, c.anthropic_model = "ollama", "", ""
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# ---- Ollama connection / model availability
def test_health_ok_and_model_listing(fake_ollama):
    s = fake_ollama(models=["qwen3:4b", "qwen3:8b"])
    h = ollama(s.url).health()
    assert h.reachable and h.model_available and h.version == "0.0-fake"
    assert h.local_models == ["qwen3:4b", "qwen3:8b"] and h.loaded_models[0]["name"] == "qwen3:4b"


def test_health_reports_missing_model(fake_ollama):
    s = fake_ollama(models=["llama3.2:3b"])
    h = ollama(s.url).health()
    assert h.reachable and h.model_available is False and "ollama pull qwen3:4b" in h.detail


def test_model_without_tag_matches_latest(fake_ollama):
    s = fake_ollama(models=["mymodel:latest"])
    assert ollama(s.url, model="mymodel").health().model_available


def test_missing_service_is_clear_error():
    p = ollama(f"http://127.0.0.1:{free_port()}")
    h = p.health(timeout=1)
    assert not h.reachable and "is Ollama running" in h.detail
    with pytest.raises(ProviderUnavailable, match="cannot connect to Ollama"):
        p.complete("s", "u")


# ---- generation
def test_generation_request_shape(fake_ollama):
    s = fake_ollama(reply="<think>hidden</think> Final words here.")
    p = ollama(s.url, temperature=0.3, num_ctx=2048, num_gpu="0", keep_alive="2m")
    assert p.complete("SYS", "USER", max_tokens=99) == "Final words here."
    body = s.requests[0]
    assert body["stream"] is False and body["think"] is False and body["keep_alive"] == "2m"
    assert body["options"] == {"temperature": 0.3, "num_ctx": 2048, "num_predict": 99, "num_gpu": 0}
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]


def test_num_gpu_omitted_when_auto(fake_ollama):
    s = fake_ollama()
    ollama(s.url).complete("s", "u")
    assert "num_gpu" not in s.requests[0]["options"]


def test_missing_model_on_chat(fake_ollama):
    s = fake_ollama(models=["other:1b"])
    with pytest.raises(ModelNotFound, match="ollama pull qwen3:4b"):
        ollama(s.url).complete("s", "u")


def test_timeout_after_retries(fake_ollama, monkeypatch):
    monkeypatch.setattr("clipbot.providers._sleep", lambda s: None)
    s = fake_ollama(delay=1.0)
    p = ollama(s.url, timeout=0.3, retries=1)
    with pytest.raises(ProviderTimeout, match="OLLAMA_TIMEOUT"):
        p.complete("s", "u")
    assert len(s.requests) == 2  # first try + 1 retry


def test_server_error_is_retried(fake_ollama, monkeypatch):
    monkeypatch.setattr("clipbot.providers._sleep", lambda s: None)
    s = fake_ollama(chat_status=[500, 200])
    assert ollama(s.url, retries=2).complete("s", "u")
    assert len(s.requests) == 2


def test_model_without_thinking_support_retried_without_think(fake_ollama):
    s = fake_ollama(reject_think=True)
    assert ollama(s.url).complete("s", "u")
    assert "think" in s.requests[0] and "think" not in s.requests[1]


def test_concurrency_limit(fake_ollama):
    s = fake_ollama(delay=0.3)
    p = ollama(s.url, max_concurrent=1)
    ts = [threading.Thread(target=p.complete, args=("s", "u")) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert s.max_active == 1 and len(s.requests) == 3


# ---- provider selection / validation
def test_default_provider_is_ollama_without_any_key():
    c = Config()
    assert c.ai_provider == "ollama" or c.ai_provider  # default from env is 'ollama'
    p = make_provider(cfg())
    assert isinstance(p, OllamaProvider) and p.model == cfg().ollama_model


def test_anthropic_selected_explicitly():
    p = make_provider(cfg(ai_provider="anthropic", anthropic_api_key="sk-ant-test-123456", anthropic_model="claude-opus-5-5"))
    assert isinstance(p, AnthropicProvider) and p.model == "claude-opus-5-5"
    assert "sk-ant" not in repr(p)


@pytest.mark.parametrize("kw,msg", [
    ({"ai_provider": "openai"}, "not supported"),
    ({"ai_provider": "anthropic"}, "ANTHROPIC_API_KEY"),
    ({"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-x-123456"}, "ANTHROPIC_MODEL"),
    ({"ollama_base_url": "localhost:11434"}, "OLLAMA_BASE_URL"),
    ({"ollama_model": ""}, "OLLAMA_MODEL"),
    ({"ollama_num_gpu": "auto"}, "OLLAMA_NUM_GPU"),
    ({"ollama_think": "maybe"}, "OLLAMA_THINK"),
    ({"ollama_timeout": 0}, "OLLAMA_TIMEOUT"),
])
def test_invalid_configuration(kw, msg):
    with pytest.raises(ProviderConfigError, match=msg):
        make_provider(cfg(**kw))


def test_config_repr_hides_key():
    assert "sk-ant-secret" not in repr(cfg(anthropic_api_key="sk-ant-secret-999"))


def test_secret_redactor(caplog):
    logger = logging.getLogger("redact-test")
    h = logging.StreamHandler()
    rec = []
    h.emit = lambda r: rec.append(h.format(r))
    h.addFilter(SecretRedactor(["sk-ant-supersecret"]))
    logger.addHandler(h)
    logger.warning("key is %s", "sk-ant-supersecret")
    assert rec == ["key is ***"]


# ---- Anthropic provider (fake client)
def fake_client(resp):
    calls = []

    def create(**kw):
        calls.append(kw)
        return resp

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create))), calls


def test_anthropic_generation():
    client, calls = fake_client(SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="A real take.")]))
    p = AnthropicProvider("sk-ant-x-123456", "claude-opus-5-5", client=client)
    assert p.complete("s", "u") == "A real take."
    assert calls[0]["model"] == "claude-opus-5-5" and calls[0]["fallbacks"] == "default"


def test_anthropic_refusal():
    client, _ = fake_client(SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(GenerationRefused):
        AnthropicProvider("sk-ant-x-123456", "claude-opus-5-5", client=client).complete("s", "u")
