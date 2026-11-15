# ClipBot – self-hosted Shorts production

ClipBot turns authorised livestream clips into commentary YouTube Shorts:
**transcription → AI commentary → narration → captions → 9:16 video → your approval → upload**.
By default every AI step runs on your own PC: faster-whisper, **Ollama** (local LLM) and Kokoro.
No paid API is required. Anthropic is an optional alternative provider.

> Only use footage you have the rights to (streamer permission, your own footage, or a licence that allows it).
> Nothing is published until you press **Approve**. YouTube uploads default to `private`.

---

## 1. Architecture

```
            ┌──────────── worker (python -m clipbot.worker) ─────────────┐
 Twitch ──► │ discover → download → 9:16 edit → transcribe (faster-whisper)│
 (allow-    │   → AI script (provider) → narration (Kokoro) → captions    │
  listed)   │   → mix + duck + loudness + burn captions (FFmpeg)          │──► data/final/*.mp4
            │   → wait for approval → upload (YouTube / Instagram)        │
            └─────────────────────────┬───────────────────────────────────┘
                                      │ SQLite (data/clipbot.db)
            ┌─────────────────────────┴──────────────────────┐
            │ dashboard (uvicorn clipbot.dashboard:app)      │  review, edit script, change style,
            │ http://127.0.0.1:8000                          │  regenerate, approve / reject, AI status
            └────────────────────────────────────────────────┘

 AI providers (clipbot/providers.py):   AIProvider ─┬─ OllamaProvider   (default, local HTTP API)
                                                     └─ AnthropicProvider (optional, needs key)
```

| Module | Job |
|---|---|
| `clipbot/providers.py` | Provider interface, Ollama + Anthropic, config validation, health checks, retries, timeouts, key redaction |
| `clipbot/ai_commentary.py` | Prompts, 3 styles, word limits, anti-generic and anti-parroting checks, manual-review flag |
| `clipbot/transcribe.py` | faster-whisper → timestamped transcript `[mm:ss] text` |
| `clipbot/tts.py` | Kokoro narration: sentence pacing, silence trimming, pronunciation file, timing sidecar |
| `clipbot/captions.py` | Animated captions (ASS), watermark, source label |
| `clipbot/commentary.py` | FFmpeg mix: voice clean-up, ducking, loudness target, limiter, captions, H.264 |
| `clipbot/editor.py` | Download (yt-dlp) and 1080×1920 vertical edit (blurred background + full original frame) |
| `clipbot/worker.py` | Pipeline stages, resumable via clip status |
| `clipbot/dashboard.py` | Review UI and AI settings |
| `clipbot/check_env.py` | Environment check (used by `scripts\check_environment.ps1`) |

Clip status flow: `new → needs_script → (needs_manual) → script_ready → voice_ready → pending_review → approved → published`
(or `rejected` / `failed`; **Retry** resumes at the failed stage).

---

## 2. Windows installation (no Docker)

Open **PowerShell** in the project folder (the folder containing this README).

### 2.1 Install tools (Python, FFmpeg, Ollama)
```powershell
winget install --id Python.Python.3.13 -e
winget install --id Gyan.FFmpeg -e
winget install --id Ollama.Ollama -e
```
Close and reopen PowerShell so the new `PATH` is picked up. Or run all steps in one go with
`scripts\setup_windows.ps1 -InstallTools` (below).

- FFmpeg must include **libx264** and **libass** (the Gyan "full" build does). `scripts\check_environment.ps1` verifies this.
- Ollama for Windows: https://ollama.com/download/windows. It runs in the system tray and listens on `http://localhost:11434`.

### 2.2 Set up ClipBot
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1
notepad .env
```
`setup_windows.ps1` creates `.venv`, installs the pinned packages (`requirements.txt` + `requirements.lock`),
creates `.env` from `.env.example` and runs the environment check. It downloads **no** models unless you ask:

```powershell
.\scripts\setup_windows.ps1 -DownloadSpeechModels      # Kokoro (~90 MB) + Whisper base.en (~150 MB)
.\scripts\setup_windows.ps1 -PullModel                 # ollama model from OLLAMA_MODEL (qwen3:4b)
.\scripts\setup_windows.ps1 -InstallTools -DownloadSpeechModels -PullModel   # everything
```

### 2.3 Download models (explicit, one time)
```powershell
.\.venv\Scripts\python scripts\download_models.py --speech     # Kokoro + Whisper
ollama pull qwen3:4b                                           # or: .\.venv\Scripts\python scripts\download_models.py --ollama
.\.venv\Scripts\python scripts\download_models.py --list       # models installed in Ollama
```

### 2.4 Check the environment
```powershell
.\scripts\check_environment.ps1
```
It checks: Windows, RAM, CPU, NVIDIA GPU (`nvidia-smi`), disk space, ffmpeg/ffprobe/ollama on PATH, Python,
FFmpeg libx264/libass, the Ollama connection, the configured model, and the Kokoro and Whisper files.

### 2.5 Start ClipBot
```powershell
.\scripts\start_clipbot.ps1                  # worker + dashboard, Ctrl+C stops both
.\scripts\start_clipbot.ps1 -DashboardOnly   # just the review UI
```
Dashboard: http://127.0.0.1:8000 (user/password = `DASHBOARD_USER` / `DASHBOARD_PASSWORD` in `.env`; change the password).
Logs: `data\logs\worker.log`, `data\logs\dashboard.log`.

### 2.6 Process your own clip (no Twitch needed)
```powershell
.\.venv\Scripts\python scripts\process_local_video.py C:\clips\my_clip.mp4 --streamer "MyFriend" --style funny
```
The clip then appears in the dashboard for review. It is never published by this script.

---

## 3. Configuration (`.env`)

All options are documented in `.env.example`. The main ones:

| Variable | Default | Meaning |
|---|---|---|
| `AI_PROVIDER` | `ollama` | `ollama` (local) or `anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `qwen3:4b` | Any model shown by `ollama list` |
| `OLLAMA_TIMEOUT` | `180` | Seconds per request (first request includes model load time) |
| `OLLAMA_TEMPERATURE` | `0.7` | Creativity |
| `OLLAMA_NUM_GPU` | *(empty)* | Empty = Ollama decides; `0` = CPU only |
| `OLLAMA_THINK` | `false` | qwen3 "thinking" off = faster; `omit` for models without the option |
| `AI_MAX_CONCURRENT` | `1` | Parallel AI requests |
| `AI_MAX_TRANSCRIPT_CHARS` / `AI_MAX_SCRIPT_WORDS` | `4000` / `140` | Limits |
| `AI_MIN_TRANSCRIPT_WORDS` | `8` | Fewer words → clip goes to **manual review** (no invented commentary) |
| `COMMENTARY_STYLE` | `storytelling` | `storytelling`, `funny`, `hype` (changeable per clip) |
| `KOKORO_VOICE` | `am_michael` | Voice, no code change needed |
| `KOKORO_SPEED`, `KOKORO_SENTENCE_PAUSE_MS` | `1.05`, `180` | Pacing |
| `PRONUNCIATION_FILE` | `clipbot/pronunciations.json` | Respellings for the narrator |
| `NARRATION_DELAY_MS`, `TARGET_LUFS`, `GAME_VOLUME`, `DUCK_RATIO` | `300`, `-14`, `0.8`, `10` | Audio mix |
| `CAPTION_STYLE` | `pop` | `pop` (animated highlight), `clean`, `none` |
| `CAPTION_FONT`, `CAPTION_FONT_SIZE`, `CAPTION_COLOR`, `CAPTION_HIGHLIGHT_COLOR`, `CAPTION_POSITION`, `CAPTION_WORDS` | | Caption look |
| `WATERMARK_TEXT`, `SOURCE_LABEL` | empty, `true` | Optional watermark; "Clip: streamer on Twitch" label |
| `AUTO_APPROVE` | `false` | Keep `false`: manual approval |
| `YT_PRIVACY` | `private` | Upload visibility |

### Switching providers
```powershell
# local (default) – no key needed
AI_PROVIDER=ollama
OLLAMA_MODEL=qwen3:4b

# Anthropic (paid, optional)
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-5-5
```
Edit `.env`, then restart `start_clipbot.ps1`. An invalid combination stops the worker at startup with a clear
message (e.g. `AI_PROVIDER=anthropic needs ANTHROPIC_API_KEY`). ClipBot never switches providers on its own
and never falls back to a canned script. A failed generation shows up as a failed clip and under **Last AI error**.

---

## 4. Testing

### Unit tests (mocked, no models needed)
```powershell
.\.venv\Scripts\python -m pytest
```
These use a **mock** Ollama server (`tests/fake_ollama.py`, a real local HTTP server with canned replies),
a mock Anthropic client and a mock Kokoro engine. Captions, mixing and the 9:16 encode run on **real FFmpeg**.
Passing unit tests do **not** prove that a real model works.

### Real integration tests (your hardware)
```powershell
# 1. AI provider with the real model (Ollama running, model pulled)
.\.venv\Scripts\python scripts\test_ai.py
.\.venv\Scripts\python -m pytest -m integration tests\integration\test_real_ollama.py -s

# 2. Real Whisper + Kokoro + captions + FFmpeg on a clip with speech you have rights to
$env:CLIPBOT_TEST_VIDEO = "C:\clips\test_with_speech.mp4"
.\.venv\Scripts\python -m pytest -m integration tests\integration\test_real_speech_pipeline.py -s

# 3. Whole pipeline on one clip, then review it in the dashboard
.\.venv\Scripts\python scripts\process_local_video.py C:\clips\test_with_speech.mp4 --style hype
```
`scripts\test_ai.py` prints provider health, then one script per style with the time each took.

---

## 5. Hardware recommendations (i7-13th gen, 32 GB RAM, GTX 1050)

| Model | Approx. download | Notes |
|---|---|---|
| `qwen3:4b` (default) | ~2.5 GB | Good quality/speed balance on CPU; fits easily in 32 GB RAM |
| `qwen3:8b` | ~5 GB | Better writing, roughly half the speed of 4b on CPU |
| `llama3.2:3b` | ~2 GB | Faster fallback; set `OLLAMA_THINK=omit` |
| `gemma3:4b` | ~3.3 GB | Alternative 4B model; set `OLLAMA_THINK=omit` |

Sizes are approximate. Check the model pages on https://ollama.com/library before pulling.

- **GPU:** a GTX 1050 has 2–4 GB VRAM (1050: 2 or 3 GB, 1050 Ti: 4 GB), less than `qwen3:4b` needs in full.
  Ollama then splits layers between GPU and CPU or uses the CPU alone. That works, but don't expect a big
  speed-up. Check what happened with `ollama ps` (the PROCESSOR column) or under "Loaded now" in the dashboard.
  Ollama's GPU support list is at https://docs.ollama.com/gpu. Set `OLLAMA_NUM_GPU=0` to force CPU if GPU use causes errors.
- **CPU:** a 13th-gen i7 should write a ~70-word script in tens of seconds with `qwen3:4b`. Measure it with
  `scripts\test_ai.py`. The first request also loads the model, so it's slower; `OLLAMA_TIMEOUT=180` allows for that.
- **RAM:** 32 GB is enough for Whisper + Kokoro + one 4B/8B model. Keep `AI_MAX_CONCURRENT=1`.
- **Whisper on GPU** (`WHISPER_DEVICE=cuda`) needs CUDA 12 + cuDNN. Leave it on `cpu` unless you've verified that.

---

## 6. Optional: Docker Compose
```powershell
docker compose up -d --build                       # uses the Ollama app on the Windows host
docker compose --profile ollama up -d --build      # or Ollama in a container (CPU); set DOCKER_OLLAMA_BASE_URL=http://ollama:11434
```
The dashboard is published on `127.0.0.1:8000` only. Models live in `.\data\models` (shared with the native setup).

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot connect to Ollama at http://localhost:11434` | Start the Ollama app (tray icon) or run `ollama serve`; check with `curl.exe http://localhost:11434/api/version` |
| `model 'qwen3:4b' is not installed` | `ollama pull qwen3:4b`, then `ollama list` |
| `Ollama did not answer within 180s` | The first load is slow: retry, raise `OLLAMA_TIMEOUT`, or use a smaller model |
| `does not support thinking` in logs | Harmless: ClipBot retries without it. Set `OLLAMA_THINK=omit` for that model |
| Clip in **needs_manual** | Too little speech. Write the script on the Review page or reject the clip |
| `ffmpeg/ffprobe not found` | Reopen PowerShell after installing, or set `FFMPEG_BIN` / `FFPROBE_BIN` to full paths |
| No captions in the video | FFmpeg without libass: install the Gyan full build. `check_environment.ps1` shows `libass(captions)=True/False` |
| `Kokoro ... missing` / `Whisper model ... not available` | `.\.venv\Scripts\python scripts\download_models.py --speech` |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Dashboard shows an old video | It reloads by version; press Ctrl+F5 if needed |

---

## 8. Publishing setup (optional)
| Credential | Where | Docs |
|---|---|---|
| `TWITCH_CLIENT_ID/SECRET` | dev.twitch.tv/console/apps | https://dev.twitch.tv/docs/authentication/register-app/ |
| `YT_CLIENT_ID/SECRET` | Google Cloud → YouTube Data API v3 → OAuth client (Desktop) | https://developers.google.com/youtube/v3/guides/uploading_a_video |
| `YT_REFRESH_TOKEN` | `.\.venv\Scripts\python scripts\youtube_auth.py client_secret.json` | |
| `IG_USER_ID / IG_ACCESS_TOKEN` | Meta app, IG Business/Creator account | https://developers.facebook.com/docs/instagram-platform/content-publishing |

## 9. Know before publishing
- **Permission:** only allow-list streamers who agreed in writing.
- **YouTube:** uploads from unverified API projects stay private until the project passes an audit; the default quota allows about 6 uploads/day. https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits
- **Monetisation:** YouTube can refuse to monetise reused content with little original value. Edit scripts so each one has a real take. https://support.google.com/youtube/answer/1311392
- **Instagram:** needs Meta App Review for `instagram_content_publish`, and API posts are rate-limited.

See `AUDIT_REPORT.md` for the last technical audit.
