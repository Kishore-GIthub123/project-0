"""AI provider abstraction: Ollama (local, default) and Anthropic (optional).

Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md (moving to https://docs.ollama.com/api)
Anthropic API: https://platform.claude.com/docs/en/api/messages
"""
from __future__ import annotations

import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

log = logging.getLogger("clipbot.ai")

PROVIDERS = ("ollama", "anthropic")


# ---------------------------------------------------------------- errors
class ProviderError(RuntimeError):
    """Base class. Messages are safe to show in the dashboard (never contain secrets)."""


class ProviderConfigError(ProviderError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class ModelNotFound(ProviderError):
    pass


class ProviderTimeout(ProviderError):
    pass


class GenerationRefused(ProviderError):
    pass


@dataclass
class Health:
    provider: str
    model: str
    reachable: bool
    model_available: bool | None
    detail: str = ""
    version: str | None = None
    local_models: list[str] = field(default_factory=list)
    loaded_models: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- interface
class AIProvider(ABC):
    name: str
    model: str

    def __init__(self, max_concurrent: int = 1):
        self._slots = threading.BoundedSemaphore(max(1, max_concurrent))

    @abstractmethod
    def health(self, timeout: float = 5) -> Health: ...

    @abstractmethod
    def _complete(self, system: str, prompt: str, max_tokens: int) -> str: ...

    def complete(self, system: str, prompt: str, max_tokens: int = 1024) -> str:
        """Return the model's text reply. Raises a ProviderError subclass on any failure."""
        with self._slots:  # caps concurrent AI jobs (AI_MAX_CONCURRENT)
            return self._complete(system, prompt, max_tokens)


# ---------------------------------------------------------------- Ollama
def _sleep(seconds: float):  # separate function so tests can skip back-off waits
    time.sleep(seconds)


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 180, temperature: float = 0.7,
                 retries: int = 2, num_ctx: int = 4096, num_gpu: str = "", keep_alive: str = "5m",
                 think: str = "false", max_concurrent: int = 1, session: requests.Session | None = None):
        super().__init__(max_concurrent)
        self.base_url, self.model = base_url.rstrip("/"), model
        self.timeout, self.temperature, self.retries = timeout, temperature, max(0, retries)
        self.num_ctx, self.num_gpu, self.keep_alive = num_ctx, num_gpu, keep_alive
        self.think = think
        self.http = session or requests.Session()
        self.http.trust_env = False if _is_local(self.base_url) else self.http.trust_env  # no proxy for localhost

    # -- discovery
    def version(self, timeout: float = 5) -> str:
        r = self._get("/api/version", timeout)
        return r.json().get("version", "?")

    def list_models(self, timeout: float = 5) -> list[str]:
        r = self._get("/api/tags", timeout)
        return sorted(m.get("name") or m.get("model") for m in r.json().get("models", []))

    def loaded_models(self, timeout: float = 5) -> list[dict]:
        r = self._get("/api/ps", timeout)
        return [{"name": m.get("name"), "size": m.get("size"), "size_vram": m.get("size_vram")}
                for m in r.json().get("models", [])]

    def has_model(self, names: list[str]) -> bool:
        want = self.model if ":" in self.model else f"{self.model}:latest"
        return want in names or self.model in names

    def health(self, timeout: float = 5) -> Health:
        h = Health(self.name, self.model, reachable=False, model_available=None)
        try:
            h.version = self.version(timeout)
            h.reachable = True
            h.local_models = self.list_models(timeout)
            h.model_available = self.has_model(h.local_models)
            try:
                h.loaded_models = self.loaded_models(timeout)
            except ProviderError:
                pass
            h.detail = "ok" if h.model_available else (
                f"model '{self.model}' is not installed - run: ollama pull {self.model}")
        except ProviderError as e:
            h.detail = str(e)
        return h

    # -- generation
    def _payload(self, system: str, prompt: str, max_tokens: int, with_think: bool) -> dict:
        options = {"temperature": self.temperature, "num_ctx": self.num_ctx, "num_predict": max_tokens}
        if self.num_gpu != "":
            options["num_gpu"] = int(self.num_gpu)
        body = {"model": self.model, "stream": False, "keep_alive": self.keep_alive, "options": options,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if with_think and self.think in ("true", "false"):
            body["think"] = self.think == "true"
        elif with_think and self.think in ("low", "medium", "high"):
            body["think"] = self.think
        return body

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        with_think = self.think != "omit"
        last: ProviderError | None = None
        attempt = 0
        while attempt <= self.retries:
            if last is not None:
                _sleep(min(2 ** attempt, 10))
            attempt += 1
            try:
                r = self.http.post(f"{self.base_url}/api/chat", json=self._payload(system, prompt, max_tokens, with_think),
                                   timeout=(5, self.timeout))
            except requests.exceptions.ConnectionError:
                last = ProviderUnavailable(f"cannot connect to Ollama at {self.base_url} - is Ollama running? "
                                           "(Windows: start the Ollama app, or run 'ollama serve')")
                continue
            except requests.exceptions.Timeout:
                last = ProviderTimeout(f"Ollama did not answer within {self.timeout:g}s (model loading or a slow CPU). "
                                       "Raise OLLAMA_TIMEOUT or use a smaller model.")
                continue
            if r.status_code == 404:
                if "model" in r.text.lower():
                    raise ModelNotFound(f"model '{self.model}' is not installed in Ollama - run: ollama pull {self.model}")
                raise ProviderUnavailable(f"{self.base_url}/api/chat not found - is OLLAMA_BASE_URL an Ollama server?")
            if r.status_code == 400 and with_think and "think" in r.text.lower():
                log.info("model does not accept the 'think' option; retrying without it")
                with_think = False
                attempt -= 1  # not a failure: does not use up a retry
                continue
            if r.status_code >= 500:
                last = ProviderUnavailable(f"Ollama error {r.status_code}: {_err_text(r)}")
                continue
            if r.status_code >= 400:
                raise ProviderError(f"Ollama rejected the request ({r.status_code}): {_err_text(r)}")
            data = r.json()
            text = _THINK_BLOCK.sub("", (data.get("message") or {}).get("content") or "").strip()
            if not text:
                raise ProviderError(f"Ollama returned an empty reply (done_reason={data.get('done_reason')})")
            log.info("ollama %s: %s tokens in %.1fs (load %.1fs)", self.model, data.get("eval_count"),
                     (data.get("total_duration") or 0) / 1e9, (data.get("load_duration") or 0) / 1e9)
            return text
        raise last or ProviderError("Ollama request failed")

    def pull(self, progress=print) -> None:
        """Download the configured model. Only called by scripts/pull_model.py (explicit user action)."""
        import json
        with self.http.post(f"{self.base_url}/api/pull", json={"model": self.model, "stream": True},
                            stream=True, timeout=(5, None)) as r:
            if r.status_code >= 400:
                raise ProviderError(f"pull failed ({r.status_code}): {_err_text(r)}")
            for line in r.iter_lines():
                if line:
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise ProviderError(f"pull failed: {msg['error']}")
                    progress(msg)

    def _get(self, path: str, timeout: float) -> requests.Response:
        try:
            r = self.http.get(f"{self.base_url}{path}", timeout=timeout)
        except requests.exceptions.ConnectionError:
            raise ProviderUnavailable(f"cannot connect to Ollama at {self.base_url} - is Ollama running?") from None
        except requests.exceptions.Timeout:
            raise ProviderTimeout(f"Ollama at {self.base_url} did not answer {path} within {timeout}s") from None
        if r.status_code >= 400:
            raise ProviderUnavailable(f"Ollama {path} returned {r.status_code}: {_err_text(r)}")
        return r


def _is_local(url: str) -> bool:
    return bool(re.match(r"https?://(localhost|127\.0\.0\.1|\[::1\]|host\.docker\.internal)(:|/|$)", url))


def _err_text(r: requests.Response) -> str:
    try:
        return str(r.json().get("error", r.text))[:300]
    except ValueError:
        return r.text[:300]


# ---------------------------------------------------------------- Anthropic
class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_concurrent: int = 1, client=None):
        super().__init__(max_concurrent)
        self.model = model
        self._api_key = api_key
        self._client = client

    def __repr__(self):  # never show the key
        return f"AnthropicProvider(model={self.model!r}, api_key=***)"

    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def health(self, timeout: float = 5) -> Health:
        h = Health(self.name, self.model, reachable=False, model_available=None)
        try:
            m = self.client().with_options(timeout=timeout, max_retries=0).models.retrieve(self.model)
            h.reachable, h.model_available, h.detail = True, True, f"ok ({getattr(m, 'display_name', m.id)})"
        except Exception as e:  # noqa: BLE001
            h.detail = _anthropic_error(e)
            h.reachable = "not found" in h.detail
            h.model_available = False if h.reachable else None
        return h

    def _complete(self, system: str, prompt: str, max_tokens: int) -> str:
        try:
            resp = self.client().beta.messages.create(
                model=self.model, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(_anthropic_error(e)) from None
        if resp.stop_reason == "refusal":
            raise GenerationRefused("the model declined to write this script")
        text = " ".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise ProviderError(f"empty reply (stop_reason={resp.stop_reason})")
        return text


def _anthropic_error(e: Exception) -> str:
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic rejected the API key (401)"
    if isinstance(e, anthropic.NotFoundError):
        return "Anthropic model not found - check ANTHROPIC_MODEL"
    if isinstance(e, anthropic.RateLimitError):
        return "Anthropic rate limit reached (429)"
    if isinstance(e, anthropic.APIStatusError):
        return f"Anthropic API error {e.status_code}"
    if isinstance(e, anthropic.APIConnectionError):
        return "cannot reach the Anthropic API (network)"
    return f"Anthropic error: {type(e).__name__}"


# ---------------------------------------------------------------- factory
def make_provider(cfg) -> AIProvider:
    """Build the configured provider. Raises ProviderConfigError with a readable message."""
    name = (cfg.ai_provider or "").strip().lower()
    if name not in PROVIDERS:
        raise ProviderConfigError(f"AI_PROVIDER='{cfg.ai_provider}' is not supported; use one of: {', '.join(PROVIDERS)}")
    if name == "ollama":
        if not re.match(r"^https?://", cfg.ollama_base_url or ""):
            raise ProviderConfigError("OLLAMA_BASE_URL must start with http:// or https://")
        if not cfg.ollama_model:
            raise ProviderConfigError("OLLAMA_MODEL is empty (e.g. qwen3:4b)")
        if cfg.ollama_num_gpu not in ("",) and not cfg.ollama_num_gpu.lstrip("-").isdigit():
            raise ProviderConfigError("OLLAMA_NUM_GPU must be empty (auto), 0 (CPU only) or a number of layers")
        if cfg.ollama_think not in ("true", "false", "omit", "low", "medium", "high"):
            raise ProviderConfigError("OLLAMA_THINK must be true, false, omit, low, medium or high")
        if cfg.ollama_timeout <= 0:
            raise ProviderConfigError("OLLAMA_TIMEOUT must be > 0 seconds")
        return OllamaProvider(cfg.ollama_base_url, cfg.ollama_model, cfg.ollama_timeout, cfg.ollama_temperature,
                              cfg.ai_retries, cfg.ollama_num_ctx, cfg.ollama_num_gpu, cfg.ollama_keep_alive,
                              cfg.ollama_think, cfg.ai_max_concurrent)
    if not cfg.anthropic_api_key:
        raise ProviderConfigError("AI_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
    if not cfg.anthropic_model:
        raise ProviderConfigError("AI_PROVIDER=anthropic needs ANTHROPIC_MODEL (e.g. claude-opus-5-5)")
    return AnthropicProvider(cfg.anthropic_api_key, cfg.anthropic_model, cfg.ai_max_concurrent)


class SecretRedactor(logging.Filter):
    """Logging filter that masks configured secrets if they ever appear in a log line."""

    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [s for s in secrets if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        if self.secrets:
            msg = record.getMessage()
            for s in self.secrets:
                msg = msg.replace(s, "***")
            record.msg, record.args = msg, ()
        return True
