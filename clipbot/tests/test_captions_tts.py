"""Captions + TTS. Caption rendering uses REAL ffmpeg/libass; Kokoro is MOCKED here (real run: tests/integration)."""
import json
import subprocess

import numpy as np
import pytest

from clipbot import captions, commentary, tts

SEGS = [{"text": "GTA chaos is back.", "start": 0.0, "end": 1.2}, {"text": "Nobody planned this.", "start": 1.4, "end": 2.6}]


def test_ass_helpers():
    assert captions.ass_color("#FFD400") == "&H0000D4FF"
    assert captions.ts(3725.456) == "1:02:05.46"
    assert captions.esc("a{b}\\c") == "a(b)c"
    with pytest.raises(ValueError):
        captions.ass_color("yellow")


def test_chunks_cover_segment_time():
    ch = captions.chunks(SEGS, 2)
    assert [" ".join(w for w, _ in g) for _, _, g in ch] == ["GTA chaos", "is back.", "Nobody planned", "this."]
    assert ch[0][0] == 0.0 and abs(ch[1][1] - 1.2) < 1e-6 and abs(ch[3][1] - 2.6) < 1e-6


def test_build_ass_pop_with_watermark_and_source(tmp_path):
    p = captions.build_ass(SEGS, tmp_path / "c.ass", 5, captions.CaptionStyle(words_per_line=3), offset=0.3,
                           watermark="@mychannel", source="Clip: S on Twitch")
    text = p.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "{\\k" in text and "\\t(0,120" in text            # karaoke highlight + pop animation
    assert "Dialogue: 1,0:00:00.30," in text                    # narration delay applied
    assert "@mychannel" in text and "Clip: S on Twitch" in text


def test_build_ass_none_style(tmp_path):
    assert captions.build_ass(SEGS, tmp_path / "c.ass", 5, captions.CaptionStyle(style="none")) is None
    p = captions.build_ass(SEGS, tmp_path / "c.ass", 5, captions.CaptionStyle(style="none"), watermark="w")
    assert "Caption,," not in p.read_text() and "Mark,," in p.read_text()


def test_bad_caption_settings(tmp_path):
    with pytest.raises(ValueError):
        captions.build_ass(SEGS, tmp_path / "c.ass", 5, captions.CaptionStyle(style="fancy"))
    with pytest.raises(ValueError):
        captions.build_ass(SEGS, tmp_path / "c.ass", 5, captions.CaptionStyle(position="left"))


def _video(path, seconds=3):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=blue:s=1080x1920:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(path)], check=True)


def _frame(path, t):
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
                           "-f", "rawvideo", "-pix_fmt", "gray", "-s", "108x192", "-"], capture_output=True).stdout


def test_ffmpeg_burns_captions_h264_1080x1920(tmp_path):
    """REAL ffmpeg: captions change the pixels, output is H.264 1080x1920 9:16 with full-length audio."""
    vid, voice = tmp_path / "v.mp4", tmp_path / "n.wav"
    _video(vid)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=2", str(voice)], check=True)
    ass = captions.build_ass(SEGS, tmp_path / "subs dir" / "c.ass", 3, captions.CaptionStyle())  # path with a space
    plain = commentary.mix(vid, voice, tmp_path / "plain.mp4")
    subbed = commentary.mix(vid, voice, tmp_path / "subbed.mp4", subtitles=ass, delay_ms=300)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                      "stream=codec_name,width,height,pix_fmt,codec_type,duration", "-of", "json",
                                      str(subbed)], capture_output=True, text=True).stdout)["streams"]
    v = next(s for s in info if s["codec_type"] == "video")
    a = next(s for s in info if s["codec_type"] == "audio")
    assert (v["codec_name"], v["width"], v["height"], v["pix_fmt"]) == ("h264", 1080, 1920, "yuv420p")
    assert abs(float(a["duration"]) - float(v["duration"])) < 0.1
    diff = np.abs(np.frombuffer(_frame(plain, 1.0), np.uint8).astype(int) - np.frombuffer(_frame(subbed, 1.0), np.uint8))
    assert diff.max() > 50  # caption pixels present


class FakeKokoro:
    """MOCK Kokoro engine: 0.1 s silence + 0.5 s tone + 0.1 s silence per call; records spoken text."""
    def __init__(self):
        self.spoken = []

    def create(self, text, voice, speed, lang):
        self.spoken.append(text)
        sr = 24000
        tone = 0.3 * np.sin(np.linspace(0, 2 * np.pi * 220 * 0.5, int(sr * 0.5)))
        return np.concatenate([np.zeros(2400), tone, np.zeros(2400)]).astype(np.float32), sr


def test_tts_pronunciation_pacing_timings(tmp_path):
    eng = FakeKokoro()
    out = tts.speak("GTA chaos is back. Nobody planned this!", tmp_path / "v.wav", tmp_path, "am_michael", 1.0,
                    pause_ms=200, pronunciations={"GTA": "G T A"}, engine=eng)
    assert eng.spoken == ["G T A chaos is back.", "Nobody planned this!"]    # respelled for the voice only
    meta = json.loads(out.with_suffix(".json").read_text())
    assert [s["text"] for s in meta["segments"]] == ["GTA chaos is back.", "Nobody planned this!"]  # captions keep original
    s0, s1 = meta["segments"]
    assert 0.5 < s0["end"] - s0["start"] < 0.62          # leading/trailing silence trimmed (40 ms pad kept)
    assert abs((s1["start"] - s0["end"]) - 0.2) < 0.01   # configured pause between sentences


def test_trim_silence_and_split():
    sr = 1000
    a = np.concatenate([np.zeros(500), np.ones(100) * 0.5, np.zeros(500)]).astype(np.float32)
    assert len(tts.trim_silence(a, sr, pad_ms=10)) == 120
    assert tts.trim_silence(np.zeros(100, np.float32), sr).size == 0
    assert tts.split_sentences("One. Two!  Three? ...") == ["One.", "Two!", "Three?"]


def test_pronunciation_whole_words_only():
    assert tts.apply_pronunciations("GTA and GTAs and GTA6", {"GTA": "G T A", "GTA6": "G T A six"}) == "G T A and GTAs and G T A six"


def test_models_not_downloaded_without_permission(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTO_DOWNLOAD_SPEECH_MODELS", raising=False)
    with pytest.raises(tts.ModelMissing, match="download_models.py"):
        tts.ensure_models(tmp_path, "am_michael")
