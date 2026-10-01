"""Unit tests for the sandforge SDK against a tiny in-process mock API."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sandforge import Sandbox  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    created_body = None
    exec_bodies = []
    timeout_body = None

    def log_message(self, *_):
        pass

    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        if self.path == "/v1/sandboxes":
            _Handler.created_body = json.loads(raw)
            self._json(201, {"id": "sb_test", "template": "node-20",
                             "status": "running", "url": "https://x/preview/sb_test/3000/"})
        elif self.path.endswith("/exec"):
            _Handler.exec_bodies.append(json.loads(raw))
            self._json(200, {"stdout": "hello\n", "stderr": "", "exit_code": 0})
        elif self.path.endswith("/files"):
            self._json(200, {})
        elif self.path.endswith("/timeout"):
            _Handler.timeout_body = json.loads(raw)
            self._json(200, {"status": "ok"})
        else:
            self._json(200, {"ok": True})

    def do_DELETE(self):
        self._json(200, {"status": "destroyed"})

    def do_GET(self):
        if self.path == "/v1/sandboxes":
            self._json(200, {"sandboxes": [{"id": "sb_test", "status": "running"}]})
        elif self.path.startswith("/v1/sandboxes/"):
            self._json(200, {"id": "sb_test", "template": "node-20", "status": "running",
                             "url": "https://x/preview/sb_test/3000/"})
        else:
            self._json(404, {"error": "not found"})


@pytest.fixture
def server(monkeypatch):
    _Handler.created_body = None
    _Handler.exec_bodies = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setenv("SANDFORGE_API_URL", base)
    monkeypatch.setenv("SANDFORGE_API_KEY", "sfc_test")
    yield base
    httpd.shutdown()


def test_create_forwards_all_flags(server):
    with Sandbox.create(template="node-20", image="ghcr.io/me/app:1",
                        start="npm run dev", ports=[3000, 8080],
                        env={"NODE_ENV": "production"}, vcpu=2, mem_mb=1024,
                        storage_mb=4096, timeout=600) as sb:
        b = _Handler.created_body
        assert b["image"] == "ghcr.io/me/app:1"
        assert b["start"] == "npm run dev"
        assert b["ports"] == [3000, 8080]
        assert b["env"] == ["NODE_ENV=production"]
        assert b["vcpu"] == 2 and b["memory_mb"] == 1024 and b["storage_mb"] == 4096
        assert b["timeout"] == 600
        # Preview URL comes straight from the create response.
        assert sb.url == "https://x/preview/sb_test/3000/"


def test_run_and_run_code(server):
    with Sandbox.create() as sb:
        r = sb.run("echo hello")
        assert r.ok and r.stdout == "hello\n"
        sb.run_code("print('hi')", lang="python")
        # run_code writes a workspace file then execs `python3 <file>`.
        assert any("python3 _sf_" in e["cmd"] for e in _Handler.exec_bodies)


def test_upload_directory_tars(server, tmp_path):
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("B")
    with Sandbox.create() as sb:
        sb.upload(str(tmp_path), "app")
        # A directory upload untars server-side into the workspace.
        assert any("tar -xzf" in e["cmd"] and "app" in e["cmd"] for e in _Handler.exec_bodies)



# ── WS6 E2B-parity additions: run(env=), host(port), connect, list ──────────

def test_run_passes_env(server):
    """run(env=) sends a per-command env object (S7 SDK half)."""
    sb = Sandbox.create(template="node-20")
    _Handler.exec_bodies.clear()
    sb.run("echo hi", env={"FOO": "bar"})
    assert _Handler.exec_bodies[-1].get("env") == {"FOO": "bar"}


def test_host_builds_multiport_url(server):
    """host(port) returns the <port>-<id>.<domain> preview URL (S25 SDK surface)."""
    sb = Sandbox.create(template="node-20")
    assert sb.host(9000).endswith("/preview/sb_test/9000/")  # path-form fallback
    sb._info["url"] = "https://8000-sb_test.pilldrops.com/"
    assert sb.host(9000) == "https://9000-sb_test.pilldrops.com"


def test_connect_and_list(server):
    """connect(id) reattaches; list() returns the caller's sandboxes."""
    sb = Sandbox.connect("sb_test")
    assert sb.id == "sb_test" and sb.status == "running"
    assert any(x.get("id") == "sb_test" for x in Sandbox.list())


def test_set_timeout_sends_seconds(server):
    """The server reads "seconds"; any other field became a TTL of 0 and expired the sandbox."""
    sb = Sandbox.connect("sb_test")
    sb.set_timeout(600)
    assert _Handler.timeout_body == {"seconds": 600}
