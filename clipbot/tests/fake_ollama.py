"""MOCK Ollama server for unit tests: a real HTTP server on 127.0.0.1 that imitates the Ollama API."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, models=("qwen3:4b",), reply="A clean test script about the moment.", chat_status=None,
                 delay=0.0, reject_think=False):
        self.models, self.reply, self.chat_status, self.delay = list(models), reply, list(chat_status or []), delay
        self.reject_think = reject_think
        self.requests, self.active, self.max_active = [], 0, 0
        self._lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._send(200, {"version": "0.0-fake"})
                if self.path == "/api/tags":
                    return self._send(200, {"models": [{"name": m, "model": m, "size": 1} for m in fake.models]})
                if self.path == "/api/ps":
                    return self._send(200, {"models": [{"name": fake.models[0], "size": 10, "size_vram": 0}]
                                            if fake.models else []})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fake._lock:
                    fake.requests.append(body)
                    fake.active += 1
                    fake.max_active = max(fake.max_active, fake.active)
                try:
                    if fake.delay:
                        time.sleep(fake.delay)
                    if self.path != "/api/chat":
                        return self._send(404, {"error": "not found"})
                    if body["model"] not in fake.models:
                        return self._send(404, {"error": f"model \"{body['model']}\" not found, try pulling it first"})
                    if fake.reject_think and "think" in body:
                        return self._send(400, {"error": f"\"{body['model']}\" does not support thinking"})
                    if fake.chat_status:
                        code = fake.chat_status.pop(0)
                        if code != 200:
                            return self._send(code, {"error": "simulated failure"})
                    reply = fake.reply(body) if callable(fake.reply) else fake.reply
                    self._send(200, {"model": body["model"], "message": {"role": "assistant", "content": reply},
                                     "done": True, "done_reason": "stop", "eval_count": 42,
                                     "total_duration": 1_000_000_000, "load_duration": 100_000_000})
                finally:
                    with fake._lock:
                        fake.active -= 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
