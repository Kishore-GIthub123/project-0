"""Twitch Helix API client. Docs: https://dev.twitch.tv/docs/api/reference/"""
import time
from datetime import datetime, timedelta, timezone

import requests

HELIX = "https://api.twitch.tv/helix"


class Twitch:
    def __init__(self, client_id: str, client_secret: str):
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._exp = "", 0.0

    def _auth(self) -> dict:
        # App access token (client credentials): https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/
        if time.time() > self._exp - 60:
            r = requests.post("https://id.twitch.tv/oauth2/token", data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "grant_type": "client_credentials"}, timeout=20)
            r.raise_for_status()
            j = r.json()
            self._token, self._exp = j["access_token"], time.time() + j["expires_in"]
        return {"Client-Id": self.client_id, "Authorization": f"Bearer {self._token}"}

    def get(self, path: str, params) -> list[dict]:
        r = requests.get(f"{HELIX}/{path}", headers=self._auth(), params=params, timeout=20)
        r.raise_for_status()
        return r.json()["data"]

    def game_id(self, name: str) -> str | None:
        data = self.get("games", {"name": name})
        return data[0]["id"] if data else None

    def user_ids(self, logins: list[str]) -> dict[str, str]:
        out = {}
        for i in range(0, len(logins), 100):
            for u in self.get("users", [("login", l) for l in logins[i:i + 100]]):
                out[u["login"]] = u["id"]
        return out

    def live_streams(self, game_id: str, first: int = 20) -> list[dict]:
        return self.get("streams", {"game_id": game_id, "first": first, "type": "live"})

    def recent_clips(self, broadcaster_id: str, game_id: str, hours: int) -> list[dict]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        clips = self.get("clips", {
            "broadcaster_id": broadcaster_id, "first": 100,
            "started_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ended_at": end.strftime("%Y-%m-%dT%H:%M:%SZ")})
        return [c for c in clips if c.get("game_id") == game_id]
