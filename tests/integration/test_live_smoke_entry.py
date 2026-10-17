"""The live helper must reach a gateway or fail. A configured run that makes no request is not a pass."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _load():
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "scripts" / "tencent_live_smoke.py"
    spec = importlib.util.spec_from_file_location("tencent_live_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_disabled_smoke_makes_no_request(monkeypatch):
    monkeypatch.delenv("MEETING_LIVE", raising=False)
    assert _load().main() == 0


def test_missing_environment_is_not_a_pass(monkeypatch):
    monkeypatch.setenv("MEETING_LIVE", "1")
    monkeypatch.delenv("MEETING_BASE_URL", raising=False)
    monkeypatch.delenv("MEETING_ACCESS_TOKEN", raising=False)
    assert _load().main() == 2


def test_unreachable_gateway_is_a_failure(monkeypatch):
    monkeypatch.setenv("MEETING_LIVE", "1")
    monkeypatch.setenv("MEETING_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MEETING_ACCESS_TOKEN", "synthetic-token")
    assert _load().main() == 1


def test_ready_gateway_is_a_real_request(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health/ready":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"status": "ok", "database": True, "backend": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, fmt, *args):
            return
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("MEETING_LIVE", "1")
        monkeypatch.setenv("MEETING_BASE_URL", "http://127.0.0.1:" + str(server.server_address[1]))
        monkeypatch.setenv("MEETING_ACCESS_TOKEN", "synthetic-token")
        assert _load().main() == 0
    finally:
        server.shutdown()
        server.server_close()
