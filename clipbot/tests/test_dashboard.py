import importlib
import subprocess


def test_record_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import clipbot.config, clipbot.dashboard
    importlib.reload(clipbot.config)
    d = importlib.reload(clipbot.dashboard)
    from fastapi.testclient import TestClient
    d.db.add_clip({"id": "c1", "broadcaster_name": "S", "title": "t", "url": "u", "view_count": 1, "created_at": "x"})
    d.db.update("c1", status="needs_voiceover")
    c = TestClient(d.app)
    a = ("admin", "change-me")
    assert c.get("/clip/c1/voice").status_code == 401
    assert "Record" in c.get("/", auth=a).text
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
