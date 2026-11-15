"""Instagram Reels publishing (resumable upload).
Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
"""
import time
from pathlib import Path

import requests


def upload(cfg, path: Path, caption: str, timeout_s: int = 600) -> str:
    base = f"https://{cfg.ig_graph_host}/{cfg.ig_api_version}"
    tok = cfg.ig_access_token

    # 1. create a Reels container for resumable upload
    r = requests.post(f"{base}/{cfg.ig_user_id}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": tok}, timeout=30)
    r.raise_for_status()
    container = r.json()["id"]

    # 2. upload the local file
    data = path.read_bytes()
    r = requests.post(f"https://rupload.facebook.com/ig-api-upload/{cfg.ig_api_version}/{container}",
                      headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))},
                      data=data, timeout=300)
    r.raise_for_status()

    # 3. wait for processing
    deadline = time.time() + timeout_s
    while True:
        s = requests.get(f"{base}/{container}", params={"fields": "status_code,status", "access_token": tok},
                         timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") in ("ERROR", "EXPIRED") or time.time() > deadline:
            raise RuntimeError(f"Instagram processing failed: {s}")
        time.sleep(10)

    # 4. publish
    r = requests.post(f"{base}/{cfg.ig_user_id}/media_publish",
                      data={"creation_id": container, "access_token": tok}, timeout=30)
    r.raise_for_status()
    return r.json()["id"]
