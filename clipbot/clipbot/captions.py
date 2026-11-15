"""Animated captions as an ASS subtitle file, burned in by ffmpeg/libass.
ASS format reference: http://www.tcax.org/docs/ass-specs.htm (Aegisub / libass compatible)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

STYLES = ("pop", "clean", "none")
POSITIONS = {"lower": (2, 520), "center": (5, 0), "upper": (8, 300)}  # (ASS alignment, MarginV) on 1080x1920


@dataclass
class CaptionStyle:
    style: str = "pop"
    font: str = "Arial"
    size: int = 72
    color: str = "#FFFFFF"
    highlight: str = "#FFD400"
    position: str = "lower"
    words_per_line: int = 4

    @classmethod
    def from_config(cls, cfg) -> "CaptionStyle":
        return cls(cfg.caption_style, cfg.caption_font, cfg.caption_font_size, cfg.caption_color,
                   cfg.caption_highlight_color, cfg.caption_position, cfg.caption_words)


def ass_color(hex_color: str, alpha: int = 0) -> str:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color.strip())
    if not m:
        raise ValueError(f"colour must look like #RRGGBB, got {hex_color!r}")
    rr, gg, bb = m.group(1)[0:2], m.group(1)[2:4], m.group(1)[4:6]
    return f"&H{alpha:02X}{bb}{gg}{rr}".upper()


def ts(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunks(segments: list[dict], n: int) -> list[tuple[float, float, list[tuple[str, float]]]]:
    """Split each timed sentence into lines of n words; each word gets a duration proportional to its length."""
    out = []
    for seg in segments:
        words = seg["text"].split()
        if not words:
            continue
        dur = max(0.01, seg["end"] - seg["start"])
        weights = [len(w) + 2 for w in words]
        per = dur / sum(weights)
        t = seg["start"]
        for i in range(0, len(words), max(1, n)):
            group = [(w, wt * per) for w, wt in zip(words[i:i + n], weights[i:i + n])]
            end = t + sum(d for _, d in group)
            out.append((t, end, group))
            t = end
    return out


def build_ass(segments: list[dict], out: Path, duration: float, style: CaptionStyle, offset: float = 0.0,
              watermark: str = "", source: str = "") -> Path | None:
    if style.style not in STYLES:
        raise ValueError(f"CAPTION_STYLE must be one of {', '.join(STYLES)}")
    if style.position not in POSITIONS:
        raise ValueError(f"CAPTION_POSITION must be one of {', '.join(POSITIONS)}")
    show_captions = style.style != "none" and bool(segments)
    if not (show_captions or watermark or source):
        return None
    align, margin_v = POSITIONS[style.position]
    pop = style.style == "pop"
    primary = ass_color(style.highlight if pop else style.color)   # karaoke: colour after the word is spoken
    secondary = ass_color(style.color)                              # colour before
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Caption,{style.font},{style.size},{primary},{secondary},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"6,2,{align},70,70,{margin_v},1",
        f"Style: Mark,{style.font},34,&H66FFFFFF,&H66FFFFFF,&H99000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,9,40,40,60,1",
        f"Style: Source,{style.font},34,&H33FFFFFF,&H33FFFFFF,&H99000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,40,40,60,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if show_captions:
        for start, end, group in chunks(segments, style.words_per_line):
            if pop:
                body = "{\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)}" + " ".join(
                    f"{{\\k{max(1, int(round(d * 100)))}}}{esc(w)}" for w, d in group)
            else:
                body = esc(" ".join(w for w, _ in group))
            lines.append(f"Dialogue: 1,{ts(start + offset)},{ts(end + offset)},Caption,,0,0,0,,{body}")
    if watermark:
        lines.append(f"Dialogue: 2,{ts(0)},{ts(duration)},Mark,,0,0,0,,{esc(watermark)}")
    if source:
        lines.append(f"Dialogue: 2,{ts(0)},{ts(duration)},Source,,0,0,0,,{esc(source)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
