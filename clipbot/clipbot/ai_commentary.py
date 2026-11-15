"""Provider-independent commentary engine: transcript in, editable voiceover script out."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .providers import AIProvider, ProviderError

STYLES = {
    "storytelling": ("Storytelling",
                     "Tell it as a short story: set up the situation, the turn, and the payoff. Calm, confident, "
                     "curious tone. Explain why the moment matters."),
    "funny": ("Funny commentary",
              "Dry, observational humour about the situation and the chaos. Comic timing, a punchline near the end. "
              "Roast the situation, never the person's identity or appearance."),
    "hype": ("Hype commentary",
             "High energy, short punchy sentences, celebrate the skill, the chaos or the clutch moment. "
             "Excited but not shouting; no all-caps."),
}

GENERIC_PHRASES = ["buckle up", "you won't believe", "let's dive in", "dive into", "in this video", "without further ado",
                   "hold onto your", "wild ride", "game-changer", "game changer", "smash that", "like and subscribe",
                   "absolutely insane", "folks", "ladies and gentlemen", "jaw-dropping", "epic moment"]

SYSTEM = """You write voiceover scripts for an original gaming commentary channel that makes YouTube Shorts.
Each Short shows a short livestream moment; your script is spoken by a narrator over it.

Hard rules:
1. Base everything on the transcript and clip details you are given. Never invent events, reactions, quotes,
   outcomes or facts that are not in them. If something is unclear, stay vague rather than guess.
2. Add value: context, why the moment is interesting, unexpected or funny, and your own editorial take.
   Do not just re-tell the transcript line by line and do not quote more than a few words from it.
3. Start with a hook sentence that makes a viewer want to keep watching.
4. Natural spoken English. Short sentences. Contractions are fine. No emojis, hashtags, markdown, stage
   directions, sound effects, speaker labels or quotation marks around the whole script.
5. Avoid generic AI filler such as: {phrases}.
6. Respect the word limit exactly - the narration must fit the clip.
7. Be fair to the streamer: no insults about identity, appearance or private life.
Output only the script text, nothing else."""

_TS = re.compile(r"\[\d{1,2}:\d{2}(?:\.\d+)?\]\s*")
_LABEL = re.compile(r"^\s*(script|narrator|voiceover|voice-over|commentary)\s*:\s*", re.I)
_STAGE = re.compile(r"\s*[\[(][^\])]{0,60}[\])]\s*")
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


class InsufficientTranscript(ProviderError):
    """Too little speech to write honest commentary - clip goes to manual review."""


@dataclass
class Commentary:
    script: str
    style: str
    provider: str
    model: str
    attempts: int
    word_limit: int


def word_limit(seconds: float, max_words: int) -> int:
    return max(15, min(max_words, int(min(seconds, 58) * 2.4)))


def spoken_words(transcript: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", _TS.sub(" ", transcript or ""))


def build_prompt(title: str, streamer: str, transcript: str, seconds: float, style: str, limit: int,
                 max_chars: int) -> str:
    label, guide = STYLES[style]
    t = (transcript or "").strip()
    if len(t) > max_chars:
        t = t[:max_chars].rsplit(" ", 1)[0] + " [transcript truncated]"
    return (f"Style: {label} - {guide}\n"
            f"Streamer: {streamer}\nClip title: {title}\nClip length: {seconds:.0f} seconds\n"
            f"Word limit: at most {limit} words (aim for {max(10, limit - 10)}-{limit}).\n\n"
            "Transcript of what was said in the clip, in order, with [mm:ss] timestamps "
            "(automatic speech recognition, may contain mistakes):\n"
            f"{t}")


def clean(text: str, limit: int) -> str:
    t = _THINK.sub("", text).strip()
    t = re.sub(r"[*_#`]+", "", t)
    lines = [_LABEL.sub("", ln).strip() for ln in t.splitlines() if ln.strip()]
    t = " ".join(lines)
    t = _STAGE.sub(" ", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    t = re.sub(r"\s+", " ", t).strip().strip('"“”').strip()
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    words = t.split()
    if len(words) > limit:
        cut = " ".join(words[:limit])
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[:end + 1] if end > len(cut) * 0.5 else cut.rstrip(",;:") + "."
    return t


def problems(script: str, transcript: str) -> list[str]:
    issues = []
    low = script.lower()
    hits = [p for p in GENERIC_PHRASES if p in low]
    if hits:
        issues.append("remove these generic phrases: " + ", ".join(hits))
    sw, tw = [w.lower() for w in spoken_words(script)], [w.lower() for w in spoken_words(transcript)]
    grams = {tuple(tw[i:i + 5]) for i in range(len(tw) - 4)}
    sg = [tuple(sw[i:i + 5]) for i in range(len(sw) - 4)]
    if sg and sum(g in grams for g in sg) / len(sg) > 0.3:
        issues.append("too much of the transcript is repeated word for word; comment on it instead")
    if len(sw) < 8:
        issues.append("the script is too short")
    return issues


def write(provider: AIProvider, title: str, streamer: str, transcript: str, seconds: float, style: str,
          max_words: int = 140, max_transcript_chars: int = 4000, min_transcript_words: int = 8) -> Commentary:
    style = (style or "storytelling").lower()
    if style not in STYLES:
        raise ValueError(f"unknown commentary style '{style}' (use: {', '.join(STYLES)})")
    n = len(spoken_words(transcript))
    if n < min_transcript_words:
        raise InsufficientTranscript(
            f"transcript has {n} words (minimum {min_transcript_words}) - write the script manually or skip the clip")
    limit = word_limit(seconds, max_words)
    system = SYSTEM.format(phrases=", ".join(f'"{p}"' for p in GENERIC_PHRASES[:10]))
    prompt = build_prompt(title, streamer, transcript, seconds, style, limit, max_transcript_chars)
    max_tokens = limit * 3 + 120
    script, attempts = "", 0
    for attempts in (1, 2):
        script = clean(provider.complete(system, prompt, max_tokens), limit)
        issues = problems(script, transcript)
        if not issues:
            break
        prompt += ("\n\nYour previous draft was:\n" + script + "\n\nRewrite it and fix: " + "; ".join(issues))
    if len(spoken_words(script)) < 8:
        raise ProviderError("the model returned an unusable script (too short)")
    return Commentary(script, style, provider.name, provider.model, attempts, limit)
