# ClipBot technical audit – 2026-11-15

Source footage: *Tears of Steel* (© Blender Foundation, CC BY 3.0, mango.blender.org),
0:20–0:50 of `tears_of_steel_720p.mov` from download.blender.org (30 s, 1280×534, real English dialogue).
Reference text: the official English subtitles `TOS-en.srt` from the same site.

"REAL" = run for real in this audit. "MOCK" = only covered by unit tests with fakes.

## Successful tests

| # | Item | Result | Evidence |
|---|---|---|---|
| 1 | Source video → final MP4 | REAL, pass (after fix B1) | `Worker.run_once` with real ffmpeg / Whisper / Kokoro / mix. Output 1080×1920 H.264, 30.0 s video, 30.0 s audio, starts at 0.000 s |
| 2 | faster-whisper (`base.en`, CPU int8) on real speech | REAL, pass | 16.4 % word error rate (WER) vs the official subtitles. Errors: "Thom"→"Tom", one garbled line ("Whatever, Thom" → "Oh, what in our tongue") |
| 5 | Kokoro `am_michael` | REAL, pass | 24 kHz mono, 12.6 s, −23.9 LUFS, peak −3.2 dBFS. Re-transcribed by Whisper: 8.3 % WER vs the script |
| 6 | Mixing, ducking, clarity, sync | REAL, pass (after fix B1) | Final −13.7 LUFS, true peak −3.6 dBFS (no clipping). Controlled 6 kHz tone: −33.1 dB → −43.4 dB while the voice speaks (≈10 dB ducking), back to −35.1 dB after (the 0.8 game volume ≈ −1.9 dB). Voice still intelligible over the film dialogue: Whisper on the voice part matched the script except "Thom"→"Tom" |
| 7 | Edit script → regenerate | REAL, pass | Only `speak` + `mix` re-ran (download, transcribe and draft were not repeated). Voice and final file hashes changed, the clean vertical video was untouched. Whisper on the new final: 5.9 % WER vs the edited script |
| 8 | Dashboard approve/reject + restart | REAL, pass | Real uvicorn process: approve/reject → 303. Server killed with SIGKILL and restarted: statuses persisted in SQLite and showed on the page. Unauthenticated → 401, unknown action → 400, `/media` served `video/mp4` |
| 9a | Crash mid-pipeline | REAL, pass | Worker killed (SIGKILL) during voice generation. On restart only `speak` + `mix` ran |
| 9b | Retry after failure | REAL, pass (after fix B2) | Mix failure → Retry → only `mix` re-ran; the edited script was kept |
| 9c | Twitch outage | REAL, pass (after fix B3) | Twitch raising an error no longer stops clips already in the pipeline |
| 10 | Docker | REAL, pass | `docker build` succeeded (python:3.13-slim, ffmpeg 7.1.5). `pip check` clean, 13/13 tests pass inside the image, rebuilt with `requirements.lock` |

## Failed / not tested

| # | Item | Status | Reason |
|---|---|---|---|
| 3 | Real Claude script generation | NOT TESTED | No Anthropic API key here. A placeholder key gave `401 invalid x-api-key`, so the API is reachable. Covered only by MOCK tests |
| 4 | Model ID `claude-opus-5-5` valid | NOT TESTED | Same: `models.retrieve` needs a valid key |
| – | Twitch API, clip download (`yt-dlp` on Twitch URLs) | NOT TESTED | No Twitch credentials. The audit replaced the download with the local file |
| – | YouTube / Instagram upload | NOT TESTED | No OAuth credentials |
| – | Browser microphone recording page | NOT TESTED | Needs a real browser and microphone |

## Bugs found

| ID | Severity | Bug | Status |
|---|---|---|---|
| B1 | High | Audio ended when the voice-over ended (`sidechaincompress` stops at the shorter input): 30 s video had 12.6 s of audio | Fixed (`apad` + `atrim`); regression test fails before the fix and passes after |
| B2 | Medium | Retry restarted the whole pipeline: re-download, re-transcribe, a new paid Claude call, and the user-edited script overwritten | Fixed: Retry resumes at the failed stage; tested |
| B3 | Medium | Any Twitch error (outage, expired credentials) stopped all processing and publishing | Fixed: discovery errors are logged and the pipeline continues; tested |
| B4 | Low | Approve/reject on an unknown clip ID returned 303 | Fixed: 404; tested |
| B5 | Medium | Only 9 of 72 installed packages pinned; builds drifted (onnxruntime 1.29 locally vs 1.32 in the image) | Fixed: `requirements.lock` as pip constraints |
| B6 | Low | With no YouTube/Instagram configured, approved clips stay "approved" forever and the dashboard doesn't say why | Open (reported) |
| B7 | Low | The 24 h upload cap counts by `updated_at`, so touching a published clip can count it again | Open (reported) |
| B8 | Low | `POST /clip/{id}/approve` works from any status (e.g. before the voice exists) if called directly; the UI only offers it on Review | Open (reported) |
| B9 | Low | No CSRF protection on dashboard POST forms (Basic auth is sent cross-site) | Open (reported) |
| B10 | Info | faster-whisper 1.2.1 + PyAV 19 are incompatible; the bot decodes audio with ffmpeg instead | Worked around earlier |

## Missing configuration
- `ANTHROPIC_API_KEY` (or switch to a local provider).
- `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET`.
- `YT_CLIENT_ID` / `YT_CLIENT_SECRET` / `YT_REFRESH_TOKEN`.
- `ALLOWED_BROADCASTERS` with streamers who gave permission.
- `DASHBOARD_PASSWORD` (default `change-me`).

## Steps required from you
1. Add an Anthropic key (or use the local Ollama provider), then run:
   `python -c "import anthropic; print(anthropic.Anthropic().models.retrieve('claude-opus-5-5').id)"`
2. Add the Twitch keys and run the worker once against an allow-listed streamer to test real downloads.
3. Do one private YouTube upload (`YT_PRIVACY=private`) to verify OAuth.
