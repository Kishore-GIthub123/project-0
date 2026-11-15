import importlib
import subprocess


def test_record_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import clipbot.config, clipbot.dashboard
    importlib.reload(clipbot.config)
    d = importlib.reload(clipbot.dashboard)
    from fastapi.testclient import TestClient
    d.db.add_clip({"id": "c1", "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
    d.db.update("c1", status="pending_review", script="Original <b>script</b>", transcript="hi")
    c = TestClient(d.app)
    a = ("admin", "change-me")
    assert c.get("/clip/c1/voice").status_code == 401
    assert "Review" in c.get("/", auth=a).text
    page = c.get("/clip/c1/review", auth=a).text
    assert "Original &lt;b&gt;script&lt;/b&gt;" in page  # escaped
    r = c.post("/clip/c1/script", auth=a, data={"script": "  New take  "}, follow_redirects=False)
    assert r.status_code == 303 and d.db.all()[0]["script"] == "New take" and d.db.all()[0]["status"] == "script_ready"
    assert c.post("/clip/c1/script", auth=a, data={"script": "  "}).status_code == 400
    assert c.get("/clip/c1/voice", auth=a).status_code == 200
    voice = tmp_path / "v.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1",
                    "-c:a", "libopus", str(voice)], check=True)
    r = c.post("/clip/c1/voice", auth=a, files={"file": ("voice.webm", voice.read_bytes(), "audio/webm")},
               follow_redirects=False)
    assert r.status_code == 303
    row = d.db.all()[0]
    assert row["status"] == "voice_ready" and (tmp_path / "voice" / "c1.webm").exists()
    assert c.post("/clip/c1/voice", auth=a, files={"file": ("x.exe", b"1")}).status_code == 400


def test_retry_resumes_at_failed_stage_and_unknown_clip_404(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import clipbot.config, clipbot.dashboard
    importlib.reload(clipbot.config)
    d = importlib.reload(clipbot.dashboard)
    from fastapi.testclient import TestClient
    c, a = TestClient(d.app), ("admin", "change-me")
    expected = {"mix: boom": "voice_ready", "tts: boom": "script_ready", "script: boom": "needs_script",
                "publish: boom": "approved", "edit: boom": "new", None: "new"}
    for i, (err, want) in enumerate(expected.items()):
        cid = f"c{i}"
        d.db.add_clip({"id": cid, "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
        d.db.update(cid, status="failed", error=err, script="my edited script")
        assert c.post(f"/clip/{cid}/retry", auth=a, follow_redirects=False).status_code == 303
        row = d.db.conn.execute("SELECT status, script FROM clips WHERE id=?", (cid,)).fetchone()
        assert row["status"] == want and row["script"] == "my edited script"
    assert c.post("/clip/NOPE/approve", auth=a, follow_redirects=False).status_code == 404
