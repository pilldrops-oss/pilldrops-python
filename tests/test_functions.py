"""Unit tests for functions against a tiny in-process mock API."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilldrops import APIError, Functions  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *_):
        pass

    def _handle(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        body = raw if "/invoke" in self.path else (json.loads(raw) if raw else None)
        _Handler.calls.append((self.command, self.path, body, self.headers.get("Authorization")))
        if "/invoke" in self.path:
            self.send_response(418)
            self.send_header("Content-Type", "text/plain")
            self.send_header("X-Fn", "hi")
            self.end_headers()
            self.wfile.write(b"short and stout")
            return
        code, reply = 200, {}
        if self.path == "/v1/functions" and self.command == "GET":
            reply = {"functions": [{"name": "hello"}]}
        elif self.path == "/v1/functions":
            code, reply = 201, {"name": "hello", "public_id": ""}
        elif self.path == "/v1/functions/gone":
            code, reply = 404, {"error": "no such function"}
        elif self.path.endswith("/rename"):
            reply = {"name": "hi", "old_name_forwards_until": 1700000000}
        elif self.path.endswith("/deployments"):
            reply = {"deployments": [{"id": "d_2"}, {"id": "d_1"}]}
        elif self.path.endswith("/d_old/rollback"):
            code, reply = 409, {"error": "code not kept"}
        elif self.path.endswith("/rollback"):
            reply = {"status": "rolled back"}
        elif self.command == "PUT":
            reply = {"status": "updated"}
        elif self.command == "DELETE":
            reply = {"status": "deleted"}
        elif self.command == "GET":
            reply = {"name": "hello", "idle_timeout": 0}
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


@pytest.fixture
def base():
    _Handler.calls = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def fns(base):
    return Functions(api_url=base, api_key="sfc_test")


def test_function_methods_send_the_right_requests(fns):
    assert fns.list() == [{"name": "hello"}]
    assert fns.get("hello") == {"name": "hello", "idle_timeout": 0}
    assert fns.create("hello", "python app.py", port=8000, public=True,
                      files=[{"path": "app.py", "content": "print(1)"}])["name"] == "hello"
    assert fns.delete("hello") is None
    assert fns.rename("hello", "hi") == {"name": "hi", "old_name_forwards_until": 1700000000}
    assert fns.deployments("hello") == [{"id": "d_2"}, {"id": "d_1"}]
    assert fns.rollback("hello", "d_1") is None
    auth = "Bearer sfc_test"
    assert _Handler.calls == [
        ("GET", "/v1/functions", None, auth),
        ("GET", "/v1/functions/hello", None, auth),
        ("POST", "/v1/functions", {"name": "hello", "start": "python app.py", "port": 8000, "public": True,
                                   "files": [{"path": "app.py", "content": "print(1)"}]}, auth),
        ("DELETE", "/v1/functions/hello", None, auth),
        ("POST", "/v1/functions/hello/rename", {"name": "hi"}, auth),
        ("GET", "/v1/functions/hello/deployments", None, auth),
        ("POST", "/v1/functions/hello/deployments/d_1/rollback", None, auth),
    ]


def test_update_sends_only_the_fields_given(fns):
    assert fns.update("hello", public=False, env={}, idle_timeout=0) is None
    assert fns.update("hello", start="node app.js") is None
    assert [c[2] for c in _Handler.calls] == [{"public": False, "env": {}, "idle_timeout": 0},
                                              {"start": "node app.js"}]
    assert {c[0] for c in _Handler.calls} == {"PUT"}


def test_names_are_quoted(fns):
    fns.get("a/b c")
    fns.rollback("a/b", "d/1")
    assert [c[1] for c in _Handler.calls] == ["/v1/functions/a%2Fb%20c",
                                              "/v1/functions/a%2Fb/deployments/d%2F1/rollback"]


def test_invoke_returns_the_raw_response(fns):
    r = fns.invoke("hello", "/api/x y", method="PUT", data=b"\x00raw")
    assert r.status_code == 418
    assert r.headers["X-Fn"] == "hi"
    assert r.content == b"short and stout"
    fns.invoke("hello")
    assert _Handler.calls == [("PUT", "/v1/functions/hello/invoke/api/x%20y", b"\x00raw", "Bearer sfc_test"),
                              ("POST", "/v1/functions/hello/invoke", b"", "Bearer sfc_test")]


def test_public_invoke_sends_no_key(fns, base):
    assert fns.public_url("pub_1") == f"{base}/v1/public/functions/pub_1/invoke"
    r = fns.invoke_public("pub_1", "x", method="GET")
    assert r.status_code == 418
    assert _Handler.calls == [("GET", "/v1/public/functions/pub_1/invoke/x", b"", None)]


@pytest.mark.parametrize("status,call", [
    (404, lambda f: f.get("gone")),
    (404, lambda f: f.delete("gone")),
    (409, lambda f: f.rollback("hello", "d_old")),
])
def test_failures_raise_api_error_with_status(fns, status, call):
    with pytest.raises(APIError) as e:
        call(fns)
    assert e.value.status == status
