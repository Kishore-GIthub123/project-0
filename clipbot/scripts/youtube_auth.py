"""One-time: get a YouTube refresh token. Run locally: python scripts/youtube_auth.py client_secret.json"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    sys.argv[1], ["https://www.googleapis.com/auth/youtube.upload"])
creds = flow.run_local_server(port=8080, access_type="offline", prompt="consent")
print("YT_REFRESH_TOKEN=" + creds.refresh_token)
