# ClipBot – GTA 6 auto-clipper

Sleeps until `ACTIVATE_AT` (GTA 6 launch: **2026-11-19**), then every `POLL_SECONDS`:

1. Finds the GTA 6 category on Twitch and lists the top live streamers (your outreach list).
2. Pulls clips from **allow-listed** streamers (those who gave permission) with ≥ `MIN_CLIP_VIEWS` views.
3. Downloads each clip and converts it to 1080×1920 (Shorts/Reels format) with ffmpeg.
4. **Commentary mode** (`COMMENTARY_MODE=true`):
   transcribes the clip locally (faster-whisper) → Claude drafts original commentary →
   Kokoro voices it → the voice is cleaned up and the game audio is lowered under it.
5. Puts it in the review queue: watch the preview, edit the script (the voice regenerates), approve.
   `AUTO_APPROVE=true` skips the review.
6. Posts to YouTube Shorts and Instagram Reels within daily limits, crediting the streamer.

Dashboard (`:8000`): worker status, heartbeat, live streamers, clip queue with Approve/Reject, post links, errors.

## Setup
| Credential | Where | Docs |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude Console → API keys | https://platform.claude.com/docs/en/get-started |
| `TWITCH_CLIENT_ID/SECRET` | dev.twitch.tv/console/apps | https://dev.twitch.tv/docs/authentication/register-app/ |
| `YT_CLIENT_ID/SECRET` | Google Cloud → enable YouTube Data API v3 → OAuth client (Desktop) | https://developers.google.com/youtube/v3/guides/uploading_a_video |
| `YT_REFRESH_TOKEN` | `python scripts/youtube_auth.py client_secret.json` | |
| `IG_USER_ID / IG_ACCESS_TOKEN` | Meta app, IG Business/Creator account, `instagram_content_publish` permission | https://developers.facebook.com/docs/instagram-platform/content-publishing |

```bash
cp .env.example .env      # fill in values + ALLOWED_BROADCASTERS
docker compose up -d --build
# dashboard: http://<server>:8000  (DASHBOARD_USER / DASHBOARD_PASSWORD)
```
Run it on a server that stays on (any VPS).

Models (Kokoro voice ~90 MB, Whisper ~150 MB) download from Hugging Face on first use into `data/models`.

## Know before launch
- **Permission:** only allow-list streamers who agreed in writing. Reposting without it risks copyright strikes.
- **YouTube:** uploads from unverified API projects are forced to private until the project passes an audit; the default quota allows about 6 uploads/day. https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits
- **Monetisation:** YouTube can refuse to monetise reused content with little original value. Keep scripts
  specific to each clip, and edit them rather than approving generic ones. https://support.google.com/youtube/answer/1311392
- **Instagram:** needs Meta App Review for `instagram_content_publish`, and API posts are rate-limited per 24h.

## Test
```bash
pip install -r requirements.txt && pytest -q
```
