"""Live integration test: boots bin/sandboxd and drives the SDK against it.

Skips automatically if the binary or python `requests` is unavailable.
"""
import os
import re
import subprocess
import sys
import time
import tempfile
import shutil
import socket

import pytest

requests = pytest.importorskip("requests")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BIN = os.path.join(ROOT, "bin", "sandboxd")
sys.path.insert(0, os.path.join(ROOT, "sdk", "python"))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def server():
    if not os.path.exists(BIN):
        pytest.skip("bin/sandboxd not built; run: go build -o bin/sandboxd ./cmd/sandboxd/")
    port = _free_port()
    data = tempfile.mkdtemp(prefix="sbd-it-")
    proc = subprocess.Popen(
        [BIN],
        env={**os.environ, "PORT": str(port), "SANDBOXD_DATA": data},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    key = None
    deadline = time.time() + 15
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            continue
        m = re.search(r"(sf_live_[a-f0-9]+)", line)
        if m:
            key = m.group(1)
            break
    assert key, "did not capture first-run API key from server output"
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            if requests.get(base + "/health", timeout=1).ok:
                break
        except requests.RequestException:
            time.sleep(0.1)
    yield base, key
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(data, ignore_errors=True)


def test_sdk_end_to_end(server):
    base, key = server
    os.environ["E2B_API_URL"] = base
    os.environ["E2B_API_KEY"] = key
    import importlib
    import yoursandbox.sandbox as sbmod
    importlib.reload(sbmod)
    Sandbox = sbmod.Sandbox

    sb = Sandbox.create(template="python-3.11")
    try:
        assert sb.run("echo sdk-ok").stdout.strip() == "sdk-ok"

        sb.filesystem.write("a.txt", "hello")
        assert sb.filesystem.read("a.txt") == "hello"

        names = [e["name"] for e in sb.filesystem.list(".")]
        assert "a.txt" in names

        sb.filesystem.move("a.txt", "b.txt")
        assert sb.filesystem.stat("b.txt")["name"] == "b.txt"

        sb.filesystem.remove("b.txt")

        assert "vcpu_seconds" in sb.metrics()
    finally:
        sb.kill()
