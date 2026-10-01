"""
E2B Sandbox SDK — Full Python client for the Sandbox Platform.

Usage:
    from yoursandbox import Sandbox

    with Sandbox.create() as sb:
        sb.run("pip install requests -q")
        result = sb.run("python -c 'import requests; print(requests.__version__)'")
        print(result.stdout)

        sb.filesystem.write("hello.txt", "Hello World!")
        files = sb.filesystem.list("/")
        print(files)
"""
import logging
import os
import requests
from dataclasses import dataclass
from typing import Optional, List, Dict

logger = logging.getLogger("yoursandbox")

BASE = os.environ.get("E2B_API_URL", os.environ.get("SANDBOX_API_URL", "http://localhost:8080"))


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def raise_on_error(self) -> "ExecResult":
        if not self.success:
            raise RuntimeError(f"Command failed (exit {self.exit_code}):\n{self.stderr}")
        return self


class _Filesystem:
    """Filesystem operations for a sandbox."""

    def __init__(self, sandbox_id: str, session: requests.Session, base: str):
        self._id = sandbox_id
        self._s = session
        self._base = base

    def write(self, path: str, content: "str | bytes") -> None:
        if isinstance(content, str): content = content.encode()
        self._s.post(f"{self._base}/v1/sandboxes/{self._id}/files",
            params={"path": path}, data=content,
            headers={"Content-Type": "application/octet-stream"}, timeout=30).raise_for_status()

    def read(self, path: str) -> str:
        r = self._s.get(f"{self._base}/v1/sandboxes/{self._id}/files",
            params={"path": path}, timeout=30)
        if r.status_code == 404: raise FileNotFoundError(f"No such file: {path}")
        r.raise_for_status()
        return r.text

    def list(self, path: str = "/") -> List[Dict]:
        r = self._s.get(f"{self._base}/v1/sandboxes/{self._id}/filesystem/list",
            params={"path": path}, timeout=10)
        r.raise_for_status()
        body = r.json()
        # Server wraps entries as {"entries":[…]}; return the bare list so callers
        # can iterate DirEntry dicts as the type hint promises.
        return body.get("entries", body) if isinstance(body, dict) else body

    def mkdir(self, path: str) -> None:
        self._s.post(f"{self._base}/v1/sandboxes/{self._id}/filesystem/mkdir",
            json={"path": path}, timeout=10).raise_for_status()

    def move(self, source: str, destination: str) -> None:
        self._s.post(f"{self._base}/v1/sandboxes/{self._id}/filesystem/move",
            json={"src": source, "dst": destination}, timeout=10).raise_for_status()

    def remove(self, path: str) -> None:
        self._s.post(f"{self._base}/v1/sandboxes/{self._id}/filesystem/remove",
            json={"path": path}, timeout=10)

    def stat(self, path: str) -> Dict:
        r = self._s.get(f"{self._base}/v1/sandboxes/{self._id}/filesystem/stat",
            params={"path": path}, timeout=10)
        if r.status_code == 404: raise FileNotFoundError(f"No such file: {path}")
        r.raise_for_status()
        return r.json()


class _Process:
    """Process management for a sandbox."""

    def __init__(self, sandbox_id: str, session: requests.Session, base: str):
        self._id = sandbox_id
        self._s = session
        self._base = base

    def list(self) -> List[Dict]:
        r = self._s.get(f"{self._base}/v1/sandboxes/{self._id}/process/list", timeout=10)
        r.raise_for_status()
        return r.json()

    def signal(self, pid: int, signal: str = "SIGTERM") -> None:
        self._s.post(f"{self._base}/v1/sandboxes/{self._id}/process/signal",
            json={"pid": pid, "signal": signal}, timeout=10).raise_for_status()

    def kill(self, pid: int) -> None:
        self.signal(pid, "SIGKILL")


class Sandbox:
    """Secure isolated sandbox for code execution."""

    _BASE = BASE

    def __init__(self, sandbox_id: str, session: requests.Session, info: dict = None):
        self.id = sandbox_id
        self._session = session
        self._info = info or {}
        self.filesystem = _Filesystem(sandbox_id, session, self._BASE)
        self.process = _Process(sandbox_id, session, self._BASE)

    @property
    def url(self) -> str:
        return self._info.get("url", f"{self._BASE}/sandbox/{self.id}/")

    @property
    def template(self) -> str:
        return self._info.get("template", "")

    @property
    def boot_ms(self) -> int:
        return self._info.get("boot_ms", 0)

    @property
    def app_url(self) -> Optional[str]:
        return self._info.get("app_url")

    @classmethod
    def create(cls, template: str = "python-3.11", timeout: int = 300,
               api_key: Optional[str] = None,
               files: Optional[List[Dict]] = None,
               setup: Optional[List[str]] = None,
               start: Optional[str] = None,
               port: Optional[int] = None) -> "Sandbox":
        key = api_key or os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY")
        session = requests.Session()
        if key: session.headers["Authorization"] = f"Bearer {key}"

        body = {"template": template, "timeout": timeout}
        if files: body["files"] = files
        if setup: body["setup"] = setup
        if start: body["start"] = start
        if port: body["port"] = port

        resp = session.post(f"{cls._BASE}/v1/sandboxes", json=body, timeout=120)
        if resp.status_code == 401: raise PermissionError("Invalid API key")
        if resp.status_code == 429: raise RuntimeError("Server busy")
        if not resp.ok: raise RuntimeError(f"Create failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        sb = cls(sandbox_id=data["id"], session=session, info=data)

        try:
            info_resp = session.get(f"{cls._BASE}/v1/sandboxes/{data['id']}", timeout=10)
            if info_resp.ok: sb._info.update(info_resp.json())
        except requests.RequestException as e:
            logger.debug("Failed to fetch sandbox info after create: %s", e)

        return sb

    def run(self, cmd: str, cwd: str = "", timeout: int = 30) -> ExecResult:
        resp = self._session.post(f"{self._BASE}/v1/sandboxes/{self.id}/exec",
            json={"cmd": cmd, "cwd": cwd, "timeout": timeout}, timeout=timeout + 15)
        if resp.status_code == 404: raise RuntimeError(f"Sandbox {self.id} not found")
        if resp.status_code == 403: raise PermissionError(f"Forbidden: sandbox {self.id}")
        if not resp.ok: raise RuntimeError(f"Exec failed: {resp.text}")
        d = resp.json()
        return ExecResult(stdout=d["stdout"], stderr=d["stderr"],
                          exit_code=d["exit_code"], truncated=d.get("truncated", False))

    def info(self) -> dict:
        resp = self._session.get(f"{self._BASE}/v1/sandboxes/{self.id}", timeout=10)
        resp.raise_for_status()
        self._info = resp.json()
        return self._info

    def pause(self) -> dict:
        r = self._session.post(f"{self._BASE}/v1/sandboxes/{self.id}/pause", timeout=10)
        r.raise_for_status(); return r.json()

    def resume(self) -> dict:
        r = self._session.post(f"{self._BASE}/v1/sandboxes/{self.id}/resume", timeout=10)
        r.raise_for_status(); return r.json()

    def set_timeout(self, seconds: int) -> dict:
        r = self._session.post(f"{self._BASE}/v1/sandboxes/{self.id}/timeout",
            json={"seconds": seconds}, timeout=10)
        r.raise_for_status(); return r.json()

    def refresh(self) -> dict:
        r = self._session.post(f"{self._BASE}/v1/sandboxes/{self.id}/refresh", timeout=10)
        r.raise_for_status(); return r.json()

    def logs(self) -> list:
        r = self._session.get(f"{self._BASE}/v1/sandboxes/{self.id}/logs", timeout=10)
        r.raise_for_status(); return r.json()

    def metrics(self) -> dict:
        r = self._session.get(f"{self._BASE}/v1/sandboxes/{self.id}/metrics", timeout=10)
        r.raise_for_status(); return r.json()

    def history(self) -> list:
        r = self._session.get(f"{self._BASE}/v1/sandboxes/{self.id}/history", timeout=10)
        r.raise_for_status(); return r.json()

    def kill(self) -> None:
        try:
            self._session.delete(f"{self._BASE}/v1/sandboxes/{self.id}", timeout=10)
        except requests.RequestException as e:
            logger.debug("Failed to kill sandbox %s: %s", self.id, e)

    def __enter__(self): return self
    def __exit__(self, *_): self.kill()
    def __repr__(self): return f"Sandbox(id={self.id!r}, template={self.template!r})"


class Templates:
    """List sandbox templates. Template CRUD is not yet exposed by the server."""

    def __init__(self, base_url: str = None, api_key: str = None):
        self._base = base_url or BASE
        self._s = requests.Session()
        key = api_key or os.environ.get("E2B_API_KEY", "")
        if key: self._s.headers["Authorization"] = f"Bearer {key}"

    def list(self) -> list:
        return self._s.get(f"{self._base}/v1/templates", timeout=10).json()

    def get(self, template_id: str) -> dict:
        raise NotImplementedError("server exposes only GET /v1/templates (list)")

    def create(self, *_, **__) -> dict:
        raise NotImplementedError("template creation is not supported by sandboxd yet")

    def update(self, *_, **__) -> dict:
        raise NotImplementedError("template update is not supported by sandboxd yet")

    def build(self, *_, **__) -> dict:
        raise NotImplementedError("template build is not supported by sandboxd yet")

    def delete(self, *_, **__) -> None:
        raise NotImplementedError("template delete is not supported by sandboxd yet")


class APIKeys:
    """Manage API keys."""

    def __init__(self, base_url: str = None, api_key: str = None):
        self._base = base_url or BASE
        self._s = requests.Session()
        key = api_key or os.environ.get("E2B_API_KEY", "")
        if key: self._s.headers["Authorization"] = f"Bearer {key}"

    def list(self) -> list:
        return self._s.get(f"{self._base}/v1/keys", timeout=10).json()

    def create(self, name: str = "default") -> dict:
        r = self._s.post(f"{self._base}/v1/keys", json={"name": name}, timeout=10)
        r.raise_for_status(); return r.json()

    def revoke(self, key_id: str) -> None:
        self._s.delete(f"{self._base}/v1/keys/{key_id}", timeout=10)
