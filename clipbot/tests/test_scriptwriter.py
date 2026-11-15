from types import SimpleNamespace

import pytest

from clipbot import scriptwriter


class FakeMessages:
    def __init__(self, resp):
        self.resp, self.kwargs = resp, None

    def create(self, **kw):
        self.kwargs = kw
        return self.resp


def client(resp):
    m = FakeMessages(resp)
    return SimpleNamespace(beta=SimpleNamespace(messages=m)), m


def test_draft_builds_request_and_returns_text():
    resp = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=" Nobody saw that coming. ")])
    c, m = client(resp)
    out = scriptwriter.draft("Huge heist", "Speed", "go go go", 20, "claude-opus-5-5", client=c)
    assert out == "Nobody saw that coming."
    assert m.kwargs["model"] == "claude-opus-5-5" and m.kwargs["fallbacks"] == "default"
    assert "Word limit: 50" in m.kwargs["messages"][0]["content"]


def test_refusal_raises():
    c, _ = client(SimpleNamespace(stop_reason="refusal", content=[]))
    with pytest.raises(scriptwriter.ScriptError):
        scriptwriter.draft("t", "s", "", 10, "claude-opus-5-5", client=c)
