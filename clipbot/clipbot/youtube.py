"""YouTube upload. Docs: https://developers.google.com/youtube/v3/docs/videos/insert"""
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def upload(cfg, path: Path, title: str, description: str, tags: list[str]) -> str:
    creds = Credentials(None, refresh_token=cfg.yt_refresh_token, client_id=cfg.yt_client_id,
                        client_secret=cfg.yt_client_secret, token_uri="https://oauth2.googleapis.com/token",
                        scopes=SCOPES)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    body = {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags, "categoryId": "20"},
        "status": {"privacyStatus": cfg.yt_privacy, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]
