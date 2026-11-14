"""API failures carry the HTTP status, so callers can branch on it."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilldrops import APIError, AuthError, Sandbox, Webhooks  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    status = 500

    def log_message(self, *_):
        pass

    def _reply(self):
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"nope"}')

    do_GET = do_POST = do_DELETE = _reply


@pytest.fixture()
def base():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.parametrize("status,call", [
    (429, lambda b: Sandbox.create(api_url=b, api_key="k")),
    (403, lambda b: Webhooks(api_url=b, api_key="k").list()),
    (404, lambda b: Sandbox.connect("sb-1", api_url=b, api_key="k")),
])
def test_api_failures_carry_the_status(base, status, call):
    _Handler.status = status
    with pytest.raises(APIError) as e:
        call(base)
    assert e.value.status == status
    assert e.value.body == '{"error":"nope"}'
    assert isinstance(e.value, RuntimeError)


def test_a_refused_key_is_still_a_permission_error(base):
    _Handler.status = 401
    with pytest.raises(PermissionError) as e:
        Sandbox.create(api_url=base, api_key="k")
    assert isinstance(e.value, AuthError)
    assert e.value.status == 401
