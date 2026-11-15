import pytest

from tests.fake_ollama import FakeOllama


@pytest.fixture
def fake_ollama():
    servers = []

    def make(**kw):
        s = FakeOllama(**kw)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()
