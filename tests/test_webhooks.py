"""Unit tests for org webhooks against a tiny in-process mock API."""
import hashlib
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilldrops import Webhooks, verify_webhook_signature  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_):
        pass

    def _handle(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        _Handler.calls.append((self.command, self.path, json.loads(raw) if raw else None,
                               self.headers.get("Authorization")))
        code, reply = 200, {}
        if self.path == "/v1/webhooks" and self.command == "GET":
            reply = {"webhooks": [{"id": "wh_1"}], "deliverable_events": [], "signature": {}}
        elif self.path == "/v1/webhooks":
            code, reply = 201, {"webhook": {"id": "wh_1"}, "secret": "s", "shown_once": True, "note": "n"}
        elif self.path == "/v1/webhooks/deliveries":
            reply = {"deliveries": [{"id": "d_1"}]}
        elif self.path.endswith("/test"):
            reply = {"webhook_id": "wh_1", "status": 500, "ok": False, "error": "boom"}
        elif self.path.endswith("/toggle"):
            reply = {"id": "wh_1", "enabled": False}
        elif self.path == "/v1/webhooks/gone":
            code, reply = 404, {"error": "no such webhook"}
        elif self.path == "/v1/webhooks/wh_1":
            reply = {"deleted": "wh_1"}
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    do_GET = do_POST = do_DELETE = _handle


@pytest.fixture
def hooks():
    _Handler.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield Webhooks(api_url=f"http://127.0.0.1:{httpd.server_address[1]}", api_key="sfc_test")
    httpd.shutdown()


def test_webhook_methods_send_the_right_requests(hooks):
    assert hooks.list() == [{"id": "wh_1"}]
    created = hooks.create("https://example.com/hook", ["sandbox.ended"])
    assert created["secret"] == "s" and created["webhook"]["id"] == "wh_1"
    assert hooks.delete("wh_1") is None
    assert hooks.test("wh_1")["ok"] is False
    assert hooks.set_enabled("wh_1", False) == {"id": "wh_1", "enabled": False}
    assert hooks.deliveries() == [{"id": "d_1"}]
    auth = "Bearer sfc_test"
    assert _Handler.calls == [
        ("GET", "/v1/webhooks", None, auth),
        ("POST", "/v1/webhooks", {"url": "https://example.com/hook", "events": ["sandbox.ended"]}, auth),
        ("DELETE", "/v1/webhooks/wh_1", None, auth),
        ("POST", "/v1/webhooks/wh_1/test", None, auth),
        ("POST", "/v1/webhooks/wh_1/toggle", {"enabled": False}, auth),
        ("GET", "/v1/webhooks/deliveries", None, auth),
    ]


def test_missing_webhook_raises(hooks):
    with pytest.raises(RuntimeError, match="not found: /v1/webhooks/gone"):
        hooks.delete("gone")


def test_verify_webhook_signature():
    secret = "whsec_test"
    body = b'{"id":"d_1","type":"sandbox.ended"}'

    def sign(ts, key=secret):
        return "sha256=" + hmac.new(key.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

    now = str(int(time.time()))
    assert verify_webhook_signature(secret, now, sign(now), body)
    assert verify_webhook_signature(secret, now, sign(now), body.decode())
    assert not verify_webhook_signature(secret, now, sign(now), body + b" ")
    assert not verify_webhook_signature(secret, now, sign(now, "other"), body)

    stale = str(int(now) - 301)
    assert not verify_webhook_signature(secret, stale, sign(stale), body)
    assert verify_webhook_signature(secret, stale, sign(stale), body, tolerance=600)
    future = str(int(now) + 301)
    assert not verify_webhook_signature(secret, future, sign(future), body)
    assert not verify_webhook_signature(secret, "abc", sign("abc"), body)
