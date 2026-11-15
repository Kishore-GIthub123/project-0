"""Draft original commentary for a clip with Claude (Anthropic API).
Docs: https://platform.claude.com/docs/en/api/messages
"""
import anthropic

SYSTEM = """You write voiceover scripts for a gaming commentary channel's YouTube Shorts.
The channel reacts to and analyses short moments from GTA 6 livestreams.

Rules:
- Write ORIGINAL commentary in the channel narrator's own voice: react, explain why the moment is
  funny or impressive, add analysis or a take. Never just narrate what happens on screen.
- Do not quote long stretches of the streamer's words; refer to them briefly at most.
- Only state facts supported by the clip title or transcript. Don't invent events.
- Spoken English: short sentences, natural rhythm, casual but clean. No slurs, no insults about
  the streamer, no emojis, hashtags, stage directions or speaker labels.
- Open with a hook in the first sentence.
- Stay within the word limit you are given.
Output only the script text."""


class ScriptError(RuntimeError):
    pass


def draft(title: str, streamer: str, transcript: str, seconds: float, model: str,
          client: anthropic.Anthropic | None = None) -> str:
    client = client or anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    words = max(15, int(min(seconds, 55) * 2.5))
    prompt = (f"Streamer: {streamer}\nClip title: {title}\nClip length: {seconds:.0f}s\n"
              f"Word limit: {words}\n\nTranscript of the clip (auto-generated, may be imperfect):\n"
              f"{transcript or '(no speech detected)'}")
    try:
        resp = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError as e:
        raise ScriptError(f"rate limited: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise ScriptError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ScriptError(f"network error: {e}") from e
    if resp.stop_reason == "refusal":
        raise ScriptError("model declined to write this script")
    text = " ".join(b.text for b in resp.content if b.type == "text").strip()
    if not text:
        raise ScriptError(f"empty script (stop_reason={resp.stop_reason})")
    return text
