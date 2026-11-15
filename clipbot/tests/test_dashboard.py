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


def _dash(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import clipbot.config, clipbot.dashboard
    importlib.reload(clipbot.config)
    d = importlib.reload(clipbot.dashboard)
    from fastapi.testclient import TestClient
    return d, TestClient(d.app), ("admin", "change-me")


def test_ai_settings_card_shows_ollama_status_without_secrets(tmp_path, monkeypatch, fake_ollama):
    fake = fake_ollama(models=["qwen3:4b", "qwen3:8b"])
    d, c, a = _dash(tmp_path, monkeypatch, AI_PROVIDER="ollama", OLLAMA_BASE_URL=fake.url,
                    ANTHROPIC_API_KEY="sk-ant-must-not-leak-123")
    d.db.set_kv("ai_last_error", "2026-11-15 · ollama/qwen3:4b · boom")
    page = c.get("/", auth=a).text
    assert "AI settings" in page and "qwen3:8b" in page and "Ollama 0.0-fake" in page and "boom" in page
    assert "Anthropic key: configured" in page and "sk-ant-must-not-leak" not in page
    j = c.get("/ai/status", auth=a).json()
    assert j["reachable"] and j["model_available"] and "sk-ant" not in str(j)


def test_ai_settings_card_reports_config_error(tmp_path, monkeypatch):
    d, c, a = _dash(tmp_path, monkeypatch, AI_PROVIDER="anthropic", ANTHROPIC_API_KEY="")
    assert "Configuration error: AI_PROVIDER=anthropic needs ANTHROPIC_API_KEY" in c.get("/", auth=a).text


def test_review_style_regeneration_and_rerender(tmp_path, monkeypatch):
    d, c, a = _dash(tmp_path, monkeypatch, OLLAMA_BASE_URL="http://127.0.0.1:9")
    d.db.add_clip({"id": "c1", "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
    d.db.update("c1", status="pending_review", script="s", transcript="[00:00] hi", vertical_path=str(tmp_path / "v.mp4"))
    page = c.get("/clip/c1/review", auth=a).text
    assert "<select name=style>" in page and "Funny commentary" in page and "Regenerate final video" in page
    assert c.post("/clip/c1/regenerate-script", auth=a, data={"style": "nope"}).status_code == 400
    r = c.post("/clip/c1/regenerate-script", auth=a, data={"style": "funny"}, follow_redirects=False)
    row = d.db.all()[0]
    assert r.status_code == 303 and row["status"] == "needs_script" and row["style"] == "funny" and row["transcript"]
    assert c.post("/clip/c1/rerender", auth=a).status_code == 409  # no narration yet
    voice = tmp_path / "n.wav"
    voice.write_bytes(b"x")
    d.db.update("c1", voice_path=str(voice), status="pending_review")
    assert c.post("/clip/c1/rerender", auth=a, follow_redirects=False).status_code == 303
    assert d.db.all()[0]["status"] == "voice_ready"


def test_needs_manual_review_page(tmp_path, monkeypatch):
    d, c, a = _dash(tmp_path, monkeypatch, OLLAMA_BASE_URL="http://127.0.0.1:9")
    d.db.add_clip({"id": "c1", "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
    d.db.update("c1", status="needs_manual", error="manual: transcript has 1 words", transcript="[00:00] uh")
    assert "/clip/c1/review" in c.get("/", auth=a).text
    page = c.get("/clip/c1/review", auth=a).text
    assert "Needs manual review" in page and "<button class=ok disabled>" in page
    r = c.post("/clip/c1/script", auth=a, data={"script": "Hand written."}, follow_redirects=False)
    assert r.status_code == 303 and d.db.all()[0]["status"] == "script_ready"


def test_approve_reject_workflow(tmp_path, monkeypatch):
    d, c, a = _dash(tmp_path, monkeypatch, OLLAMA_BASE_URL="http://127.0.0.1:9")
    for cid in ("a", "b"):
        d.db.add_clip({"id": cid, "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
        d.db.update(cid, status="pending_review")
    assert c.post("/clip/a/approve", auth=a, follow_redirects=False).status_code == 303
    assert c.post("/clip/b/reject", auth=a, follow_redirects=False).status_code == 303
    assert {r["id"]: r["status"] for r in d.db.all()} == {"a": "approved", "b": "rejected"}
    assert c.post("/clip/a/approve").status_code == 401
