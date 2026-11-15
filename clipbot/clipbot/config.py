import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _list(v: str) -> list[str]:
    return [x.strip().lower() for x in v.split(",") if x.strip()]


@dataclass
class Config:
    game_name: str = os.getenv("GAME_NAME", "Grand Theft Auto VI")
    activate_at: datetime = field(default_factory=lambda: datetime.fromisoformat(
        os.getenv("ACTIVATE_AT", "2026-11-19T00:00:00Z").replace("Z", "+00:00")))
    poll_seconds: int = int(os.getenv("POLL_SECONDS", "300"))
    allowed_broadcasters: list[str] = field(default_factory=lambda: _list(os.getenv("ALLOWED_BROADCASTERS", "")))
    min_clip_views: int = int(os.getenv("MIN_CLIP_VIEWS", "50"))
    lookback_hours: int = int(os.getenv("LOOKBACK_HOURS", "24"))
    commentary_mode: bool = os.getenv("COMMENTARY_MODE", "true").lower() == "true"
    # ---- AI provider (ollama = local, default; anthropic = optional, paid) ----
    ai_provider: str = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    ollama_timeout: float = float(os.getenv("OLLAMA_TIMEOUT", "180"))
    ollama_temperature: float = float(os.getenv("OLLAMA_TEMPERATURE", "0.7"))
    ollama_num_ctx: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
    # empty = let Ollama decide (GPU if usable); 0 = force CPU
    ollama_num_gpu: str = os.getenv("OLLAMA_NUM_GPU", "").strip()
    ollama_keep_alive: str = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
    ollama_think: str = os.getenv("OLLAMA_THINK", "false").strip().lower()
    ai_retries: int = int(os.getenv("AI_RETRIES", "2"))
    ai_max_concurrent: int = int(os.getenv("AI_MAX_CONCURRENT", "1"))
    ai_max_transcript_chars: int = int(os.getenv("AI_MAX_TRANSCRIPT_CHARS", "4000"))
    ai_max_script_words: int = int(os.getenv("AI_MAX_SCRIPT_WORDS", "140"))
    ai_min_transcript_words: int = int(os.getenv("AI_MIN_TRANSCRIPT_WORDS", "8"))
    commentary_style: str = os.getenv("COMMENTARY_STYLE", "storytelling").strip().lower()
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""), repr=False)
    # ANTHROPIC_MODEL wins; CLAUDE_MODEL kept for older .env files
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "") or os.getenv("CLAUDE_MODEL", "")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

    # ---- voice / audio ----
    kokoro_voice: str = os.getenv("KOKORO_VOICE", "am_michael")
    kokoro_speed: float = float(os.getenv("KOKORO_SPEED", "1.05"))
    kokoro_sentence_pause_ms: int = int(os.getenv("KOKORO_SENTENCE_PAUSE_MS", "180"))
    pronunciation_file: str = os.getenv("PRONUNCIATION_FILE", "")
    narration_delay_ms: int = int(os.getenv("NARRATION_DELAY_MS", "300"))
    target_lufs: float = float(os.getenv("TARGET_LUFS", "-14"))
    game_volume: float = float(os.getenv("GAME_VOLUME", "0.8"))
    duck_ratio: float = float(os.getenv("DUCK_RATIO", "10"))
    whisper_model: str = os.getenv("WHISPER_MODEL", "base.en")
    whisper_device: str = os.getenv("WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

    # ---- video ----
    caption_style: str = os.getenv("CAPTION_STYLE", "pop").strip().lower()   # pop | clean | none
    caption_font: str = os.getenv("CAPTION_FONT", "Arial")
    caption_font_size: int = int(os.getenv("CAPTION_FONT_SIZE", "72"))
    caption_color: str = os.getenv("CAPTION_COLOR", "#FFFFFF")
    caption_highlight_color: str = os.getenv("CAPTION_HIGHLIGHT_COLOR", "#FFD400")
    caption_position: str = os.getenv("CAPTION_POSITION", "lower").strip().lower()  # lower | center | upper
    caption_words: int = int(os.getenv("CAPTION_WORDS", "4"))
    watermark_text: str = os.getenv("WATERMARK_TEXT", "")
    source_label: bool = os.getenv("SOURCE_LABEL", "true").lower() == "true"
    keep_intermediate_files: bool = os.getenv("KEEP_INTERMEDIATE_FILES", "false").lower() == "true"
    auto_approve: bool = os.getenv("AUTO_APPROVE", "false").lower() == "true"

    twitch_client_id: str = os.getenv("TWITCH_CLIENT_ID", "")
    twitch_client_secret: str = os.getenv("TWITCH_CLIENT_SECRET", "")

    yt_client_id: str = os.getenv("YT_CLIENT_ID", "")
    yt_client_secret: str = os.getenv("YT_CLIENT_SECRET", "")
    yt_refresh_token: str = os.getenv("YT_REFRESH_TOKEN", "")
    yt_privacy: str = os.getenv("YT_PRIVACY", "private")
    yt_daily_limit: int = int(os.getenv("YT_DAILY_LIMIT", "6"))

    ig_user_id: str = os.getenv("IG_USER_ID", "")
    ig_access_token: str = os.getenv("IG_ACCESS_TOKEN", "")
    ig_graph_host: str = os.getenv("IG_GRAPH_HOST", "graph.facebook.com")
    ig_api_version: str = os.getenv("IG_API_VERSION", "v23.0")
    ig_daily_limit: int = int(os.getenv("IG_DAILY_LIMIT", "25"))

    dashboard_user: str = os.getenv("DASHBOARD_USER", "admin")
    dashboard_password: str = os.getenv("DASHBOARD_PASSWORD", "change-me")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))

    @property
    def youtube_enabled(self) -> bool:
        return bool(self.yt_client_id and self.yt_client_secret and self.yt_refresh_token)

    @property
    def instagram_enabled(self) -> bool:
        return bool(self.ig_user_id and self.ig_access_token)
