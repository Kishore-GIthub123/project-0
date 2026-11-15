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
    auto_approve: bool = os.getenv("AUTO_APPROVE", "false").lower() == "true"

    twitch_client_id: str = os.getenv("TWITCH_CLIENT_ID", "")
    twitch_client_secret: str = os.getenv("TWITCH_CLIENT_SECRET", "")

    yt_client_id: str = os.getenv("YT_CLIENT_ID", "")
    yt_client_secret: str = os.getenv("YT_CLIENT_SECRET", "")
    yt_refresh_token: str = os.getenv("YT_REFRESH_TOKEN", "")
    yt_privacy: str = os.getenv("YT_PRIVACY", "public")
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
