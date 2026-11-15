"""MOCKED unit tests for the commentary engine (scripted fake provider)."""
import pytest

from clipbot import ai_commentary as ac
from clipbot.providers import AIProvider, Health

TRANSCRIPT = """[00:00] Chat look we are inside the bank right now
[00:04] The alarm is going off go go go
[00:09] Wait why is the getaway car on fire who did that"""


class Scripted(AIProvider):
    name, model = "fake", "fake-1"

    def __init__(self, replies):
        super().__init__()
        self.replies, self.prompts = list(replies), []

    def health(self, timeout=5):
        return Health("fake", "fake-1", True, True)

    def _complete(self, system, prompt, max_tokens):
        self.prompts.append((system, prompt, max_tokens))
        return self.replies.pop(0)


GOOD = "A heist with no plan is still a plan. He walks in confident, the alarm hits, and the getaway car is on fire. Bold."


def test_prompt_contains_transcript_style_and_limit():
    p = Scripted([GOOD])
    c = ac.write(p, "Heist", "Streamer", TRANSCRIPT, 20, "funny")
    system, prompt, max_tokens = p.prompts[0]
    assert "[00:09] Wait why is the getaway car on fire" in prompt
    assert "Funny commentary" in prompt and f"at most {c.word_limit} words" in prompt
    assert "Never invent events" in system and c.style == "funny" and c.attempts == 1
    assert max_tokens == c.word_limit * 3 + 120


@pytest.mark.parametrize("style", list(ac.STYLES))
def test_all_styles_supported(style):
    assert ac.write(Scripted([GOOD]), "t", "s", TRANSCRIPT, 30, style).style == style


def test_invalid_style():
    with pytest.raises(ValueError, match="unknown commentary style"):
        ac.write(Scripted([GOOD]), "t", "s", TRANSCRIPT, 30, "sad")


@pytest.mark.parametrize("transcript", ["", "[00:00] uh", "[00:00] go go go"])
def test_insufficient_transcript_flags_manual_review(transcript):
    p = Scripted([GOOD])
    with pytest.raises(ac.InsufficientTranscript):
        ac.write(p, "t", "s", transcript, 30, "hype")
    assert p.prompts == []  # the model is never asked to invent commentary


def test_generic_phrases_trigger_rewrite():
    p = Scripted(["Buckle up, folks, you won't believe this heist with a burning car and a loud alarm.", GOOD])
    c = ac.write(p, "t", "s", TRANSCRIPT, 30, "hype")
    assert c.attempts == 2 and c.script == GOOD and "buckle up" in p.prompts[1][1]


def test_transcript_parroting_triggers_rewrite():
    parrot = "Chat look we are inside the bank right now. The alarm is going off go go go. Wait why is the getaway car on fire."
    p = Scripted([parrot, GOOD])
    assert ac.write(p, "t", "s", TRANSCRIPT, 30, "storytelling").attempts == 2
    assert "repeated word for word" in p.prompts[1][1]


def test_clean_strips_labels_markdown_stage_directions_and_limits_words():
    raw = '<think>plan</think>**Script:** "Okay. (laughs) This is a moment 🔥. Another sentence here. And more words follow."'
    assert ac.clean(raw, 100) == "Okay. This is a moment. Another sentence here. And more words follow."
    long = " ".join(["Word"] * 30) + ". Tail."
    assert len(ac.clean(long, 10).split()) <= 10


def test_word_limit_scales_with_duration():
    assert ac.word_limit(10, 140) == 24 and ac.word_limit(120, 140) == 139 and ac.word_limit(2, 140) == 15


def test_long_transcript_truncated():
    prompt = ac.build_prompt("t", "s", "word " * 5000, 30, "hype", 50, max_chars=200)
    assert "[transcript truncated]" in prompt and len(prompt) < 1200
