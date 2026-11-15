"""Monitoring dashboard: worker status, live GTA 6 streamers, clip queue, approve/reject."""
import html
import json
import secrets

from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Config
from .db import DB

cfg = Config()
db = DB(cfg.data_dir / "clipbot.db")
app = FastAPI(title="ClipBot")
security = HTTPBasic()


def auth(c: HTTPBasicCredentials = Depends(security)):
    ok = (secrets.compare_digest(c.username, cfg.dashboard_user)
          and secrets.compare_digest(c.password, cfg.dashboard_password))
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})


e = lambda v: html.escape(str(v or ""))  # noqa: E731


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(auth)])
def index():
    counts = " · ".join(f"{k}: <b>{v}</b>" for k, v in db.counts().items()) or "no clips yet"
    live = json.loads(db.get_kv("live_top", "[]"))
    live_rows = "".join(f"<tr><td>{e(s['user'])}</td><td>{s['viewers']}</td><td>{e(s['title'])}</td></tr>"
                        for s in live)
    rows = ""
    for c in db.all():
        cid = e(c["id"])
        actions = ""
        if c["status"] == "needs_voiceover":
            actions = (f"<a class=btn href='/clip/{cid}/voice'>🎙 Record</a>"
                       f"<form method=post action='/clip/{cid}/reject'><button>Skip</button></form>")
        elif c["status"] == "pending_review":
            actions = (f"<a href='/media/{cid}' target=_blank>Preview</a> "
                       f"<form method=post action='/clip/{cid}/approve'><button>Approve</button></form>"
                       f"<form method=post action='/clip/{cid}/reject'><button>Reject</button></form>")
        elif c["status"] == "failed":
            actions = f"<form method=post action='/clip/{cid}/retry'><button>Retry</button></form>"
        yt = f"<a href='https://youtube.com/shorts/{e(c['yt_id'])}'>YT</a>" if c["yt_id"] else ""
        ig = "IG ✓" if c["ig_id"] else ""
        rows += (f"<tr><td>{e(c['status'])}</td><td>{e(c['broadcaster'])}</td>"
                 f"<td><a href='{e(c['url'])}'>{e(c['title'])}</a></td><td>{c['view_count']}</td>"
                 f"<td>{yt} {ig}</td><td class=err>{e(c['error'])}</td><td>{actions}</td>"
                 f"<td>{e(c['updated_at'])}</td></tr>")
    return f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv=refresh content=30>
<meta name=viewport content="width=device-width,initial-scale=1"><title>ClipBot</title>
<style>body{{font-family:system-ui;margin:16px;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #333;padding:6px;text-align:left;font-size:14px}}a{{color:#6cf}}
.err{{color:#f77;max-width:300px}}.btn{{background:#2a6;color:#fff;padding:4px 8px;border-radius:4px;text-decoration:none}}form{{display:inline}}.card{{background:#1c1c1c;padding:12px;border-radius:8px;margin-bottom:16px}}</style>
</head><body><h1>ClipBot · {e(cfg.game_name)}</h1>
<div class=card>Status: <b>{e(db.get_kv('status', 'not started'))}</b><br>Last heartbeat: {e(db.get_kv('heartbeat'))}<br>
{counts}<br>YouTube: {'on' if cfg.youtube_enabled else 'off'} ({db.posted_last_24h('yt_id')}/{cfg.yt_daily_limit} in 24h) ·
Instagram: {'on' if cfg.instagram_enabled else 'off'} ({db.posted_last_24h('ig_id')}/{cfg.ig_daily_limit} in 24h) ·
Auto-approve: {cfg.auto_approve}</div>
<h2>Top live {e(cfg.game_name)} streamers (outreach list)</h2>
<table><tr><th>Streamer</th><th>Viewers</th><th>Title</th></tr>{live_rows}</table>
<h2>Clips</h2><table><tr><th>Status</th><th>Streamer</th><th>Clip</th><th>Views</th><th>Posted</th>
<th>Error</th><th></th><th>Updated</th></tr>{rows}</table></body></html>"""


@app.get("/health")
def health():
    return {"status": db.get_kv("status"), "heartbeat": db.get_kv("heartbeat")}


def _clip(clip_id: str):
    row = db.conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return row


@app.get("/media/{clip_id}", dependencies=[Depends(auth)])
def media(clip_id: str):
    path = _clip(clip_id)["edited_path"]
    if not path or not Path(path).exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


@app.get("/clip/{clip_id}/voice", response_class=HTMLResponse, dependencies=[Depends(auth)])
def voice_page(clip_id: str):
    c = _clip(clip_id)
    cid = e(c["id"])
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Record commentary</title>
<style>body{{font-family:system-ui;margin:16px;background:#111;color:#eee;max-width:520px}}
video{{width:100%;max-height:60vh;background:#000}}button{{font-size:18px;padding:10px 16px;margin:6px 4px 6px 0}}
.tip{{color:#aaa;font-size:14px}}a{{color:#6cf}}</style></head><body>
<a href="/">← back</a><h2>{e(c['broadcaster'])}: {e(c['title'])}</h2>
<video id=clip src="/media/{cid}" controls playsinline></video>
<p class=tip>Tips: add your own take — what happened, why it's funny, what you'd do. Talk over the whole clip;
the game audio is lowered automatically while you speak. Use a quiet room, phone mic 15–20 cm from mouth.</p>
<button id=rec>● Record (clip plays)</button><button id=stop disabled>■ Stop</button>
<audio id=take controls style="width:100%;display:none"></audio>
<button id=save disabled>Save &amp; mix</button>
<p class=tip>No mic access (needs HTTPS)? Upload a recording instead:</p>
<form method=post enctype=multipart/form-data action="/clip/{cid}/voice">
<input type=file name=file accept="audio/*" required><button>Upload</button></form>
<script>
let rec, chunks=[], blob; const v=document.getElementById('clip');
document.getElementById('rec').onclick = async () => {{
  const s = await navigator.mediaDevices.getUserMedia({{audio:{{echoCancellation:true,noiseSuppression:true}}}});
  rec = new MediaRecorder(s); chunks=[];
  rec.ondataavailable = ev => chunks.push(ev.data);
  rec.onstop = () => {{ blob = new Blob(chunks, {{type: rec.mimeType}}); const a=document.getElementById('take');
    a.src = URL.createObjectURL(blob); a.style.display='block'; document.getElementById('save').disabled=false;
    s.getTracks().forEach(t=>t.stop()); v.pause(); }};
  v.muted = true; v.currentTime = 0; v.play(); rec.start();
  document.getElementById('stop').disabled=false; }};
document.getElementById('stop').onclick = () => rec.stop();
document.getElementById('save').onclick = async () => {{
  const f = new FormData(); f.append('file', blob, 'voice.webm');
  const r = await fetch('/clip/{cid}/voice', {{method:'POST', body:f}});
  if (r.ok) location.href='/'; else alert('Upload failed: ' + r.status); }};
</script></body></html>"""


@app.post("/clip/{clip_id}/voice", dependencies=[Depends(auth)])
async def voice_upload(clip_id: str, file: UploadFile = File(...)):
    _clip(clip_id)
    ext = Path(file.filename or "voice.webm").suffix.lower()
    if ext not in (".webm", ".ogg", ".m4a", ".mp3", ".wav", ".aac", ".mp4"):
        raise HTTPException(400, "unsupported audio format")
    data = await file.read()
    if not data or len(data) > 50_000_000:
        raise HTTPException(400, "empty or too large")
    out = cfg.data_dir / "voice" / f"{clip_id}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    db.update(clip_id, voice_path=str(out), status="voice_ready", error=None)
    return RedirectResponse("/", status_code=303)


# generic route last so /clip/{id}/voice is matched first
@app.post("/clip/{clip_id}/{action}", dependencies=[Depends(auth)])
def act(clip_id: str, action: str):
    status = {"approve": "approved", "reject": "rejected", "retry": "new"}.get(action)
    if not status:
        raise HTTPException(400)
    db.update(clip_id, status=status, error=None)
    return RedirectResponse("/", status_code=303)
