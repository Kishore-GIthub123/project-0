"""Monitoring dashboard: worker status, live GTA 6 streamers, clip queue, approve/reject."""
import html
import json
import secrets

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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
        actions = ""
        if c["status"] in ("pending_review", "failed"):
            actions = (f"<form method=post action='/clip/{e(c['id'])}/approve'><button>Approve</button></form>"
                       f"<form method=post action='/clip/{e(c['id'])}/reject'><button>Reject</button></form>")
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
.err{{color:#f77;max-width:300px}}form{{display:inline}}.card{{background:#1c1c1c;padding:12px;border-radius:8px;margin-bottom:16px}}</style>
</head><body><h1>ClipBot · {e(cfg.game_name)}</h1>
<div class=card>Status: <b>{e(db.get_kv('status', 'not started'))}</b><br>Last heartbeat: {e(db.get_kv('heartbeat'))}<br>
{counts}<br>YouTube: {'on' if cfg.youtube_enabled else 'off'} ({db.posted_last_24h('yt_id')}/{cfg.yt_daily_limit} in 24h) ·
Instagram: {'on' if cfg.instagram_enabled else 'off'} ({db.posted_last_24h('ig_id')}/{cfg.ig_daily_limit} in 24h) ·
Auto-approve: {cfg.auto_approve}</div>
<h2>Top live {e(cfg.game_name)} streamers (outreach list)</h2>
<table><tr><th>Streamer</th><th>Viewers</th><th>Title</th></tr>{live_rows}</table>
<h2>Clips</h2><table><tr><th>Status</th><th>Streamer</th><th>Clip</th><th>Views</th><th>Posted</th>
<th>Error</th><th></th><th>Updated</th></tr>{rows}</table></body></html>"""


@app.post("/clip/{clip_id}/{action}", dependencies=[Depends(auth)])
def act(clip_id: str, action: str):
    if action not in ("approve", "reject"):
        raise HTTPException(400)
    db.update(clip_id, status="approved" if action == "approve" else "rejected", error=None)
    return RedirectResponse("/", status_code=303)


@app.get("/health")
def health():
    return {"status": db.get_kv("status"), "heartbeat": db.get_kv("heartbeat")}
