"""SandForge sandbox client. See package docstring for usage."""
import io
import json
import os
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

import requests

_CONFIG_PATH = os.environ.get("SANDFORGE_CONFIG") or str(Path.home() / ".sandforge" / "config.json")


def config() -> Dict[str, str]:
    """Resolve (api_url, key) from env then ~/.sandforge/config.json.

    Env wins over the config file so CI can override a developer login. E2B_/
    SANDBOX_ names are accepted so code written against those keeps working.
    """
    url = (os.environ.get("PILLDROPS_API_URL") or os.environ.get("SANDFORGE_API_URL")
           or os.environ.get("E2B_API_URL") or os.environ.get("SANDBOX_API_URL") or "")
    key = (os.environ.get("PILLDROPS_API_KEY") or os.environ.get("SANDFORGE_API_KEY")
           or os.environ.get("E2B_API_KEY") or os.environ.get("SANDBOX_API_KEY") or "")
    if not (url and key):
        try:
            with open(_CONFIG_PATH) as f:
                c = json.load(f)
            url = url or c.get("api_url", "")
            key = key or c.get("key", "")
        except (OSError, ValueError):
            pass
    return {"api_url": url.rstrip("/"), "key": key}


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def check(self) -> "ExecResult":
        """Raise if the command failed (like subprocess.check_call)."""
        if not self.ok:
            raise RuntimeError(f"command exited {self.exit_code}:\n{self.stderr or self.stdout}")
        return self


class _Filesystem:
    def __init__(self, sb: "Sandbox"):
        self._sb = sb

    def write(self, path: str, content: Union[str, bytes]) -> None:
        if isinstance(content, str):
            content = content.encode()
        self._sb._req("POST", f"/v1/sandboxes/{self._sb.id}/files", params={"path": path},
                      data=content, headers={"Content-Type": "application/octet-stream"})

    def read(self, path: str) -> str:
        r = self._sb._req("GET", f"/v1/sandboxes/{self._sb.id}/files", params={"path": path})
        return r.text

    def list(self, path: str = "/") -> List[Dict]:
        r = self._sb._req("GET", f"/v1/sandboxes/{self._sb.id}/filesystem/list", params={"path": path})
        body = r.json()
        return body.get("entries", []) if isinstance(body, dict) else body


class Sandbox:
    """A running sandbox. Prefer `Sandbox.create(...)` and use it as a context
    manager so it is always killed."""

    def __init__(self, sandbox_id: str, session: requests.Session, base: str, info: Optional[dict] = None):
        self.id = sandbox_id
        self._s = session
        self._base = base
        self._info = info or {}
        self.files = _Filesystem(self)

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        template: str = "python-3.11",
        *,
        image: Optional[str] = None,
        start: Optional[str] = None,
        ports: Optional[List[int]] = None,
        env: Optional[Union[Dict[str, str], List[str]]] = None,
        vcpu: int = 0,
        mem_mb: int = 0,
        storage_mb: int = 0,
        timeout: int = 0,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> "Sandbox":
        cfg = config()
        base = (api_url or cfg["api_url"]).rstrip("/")
        key = api_key or cfg["key"]
        if not base:
            raise RuntimeError("no API URL — set PILLDROPS_API_URL to your PillDrops server")
        s = requests.Session()
        if key:
            s.headers["Authorization"] = f"Bearer {key}"

        # client:"sdk" tags this create as agent-originated for attribution.
        body: Dict[str, object] = {"template": template, "client": "sdk"}
        if image:
            body["image"] = image
        if start:
            body["start"] = start
        if ports:
            body["ports"] = list(ports)
        if env:
            body["env"] = ([f"{k}={v}" for k, v in env.items()] if isinstance(env, dict) else list(env))
        if vcpu:
            body["vcpu"] = vcpu
        if mem_mb:
            body["memory_mb"] = mem_mb
        if storage_mb:
            body["storage_mb"] = storage_mb
        if timeout:
            body["timeout"] = timeout

        r = s.post(f"{base}/v1/sandboxes", json=body, timeout=180)
        if r.status_code == 401:
            raise PermissionError("invalid API key — check PILLDROPS_API_KEY")
        if not r.ok:
            raise RuntimeError(f"create failed ({r.status_code}): {r.text}")
        data = r.json()
        return cls(data["id"], s, base, info=data)

    @classmethod
    def connect(cls, sandbox_id: str, *, api_url: Optional[str] = None,
                api_key: Optional[str] = None) -> "Sandbox":
        """Reattach to an existing sandbox by id (E2B Sandbox.connect parity).
        Agent processes restart; this recovers the handle without losing state."""
        cfg = config()
        base = (api_url or cfg["api_url"]).rstrip("/")
        key = api_key or cfg["key"]
        s = requests.Session()
        if key:
            s.headers["Authorization"] = f"Bearer {key}"
        r = s.get(f"{base}/v1/sandboxes/{sandbox_id}", timeout=30)
        if r.status_code == 404:
            raise RuntimeError(f"sandbox not found: {sandbox_id}")
        if not r.ok:
            raise RuntimeError(f"connect failed ({r.status_code}): {r.text[:200]}")
        return cls(sandbox_id, s, base, info=r.json())

    @classmethod
    def list(cls, *, api_url: Optional[str] = None,
             api_key: Optional[str] = None) -> List[Dict]:
        """List the caller's sandboxes (E2B Sandbox.list parity)."""
        cfg = config()
        base = (api_url or cfg["api_url"]).rstrip("/")
        key = api_key or cfg["key"]
        s = requests.Session()
        if key:
            s.headers["Authorization"] = f"Bearer {key}"
        r = s.get(f"{base}/v1/sandboxes", timeout=30)
        if not r.ok:
            raise RuntimeError(f"list failed ({r.status_code}): {r.text[:200]}")
        data = r.json()
        # The API returns either a bare list or {"sandboxes": [...]}.
        return data.get("sandboxes", data) if isinstance(data, dict) else data

    # ── properties ───────────────────────────────────────────────────────────
    @property
    def url(self) -> Optional[str]:
        """Public preview URL for the app port (None until a port is published)."""
        return self._info.get("url") or self._info.get("app_url")

    @property
    def template(self) -> str:
        return self._info.get("template", "")

    @property
    def status(self) -> str:
        return self._info.get("status") or self._info.get("state", "")

    # ── execution ────────────────────────────────────────────────────────────
    def run(self, cmd: str, cwd: str = "", timeout: int = 60,
            env: Optional[Dict[str, str]] = None) -> ExecResult:
        """Run a command. `env` injects per-command environment variables (E2B
        SDK `envs=` parity) on top of the sandbox's create-time env."""
        body: Dict[str, object] = {"cmd": cmd, "cwd": cwd, "timeout": timeout}
        if env:
            body["env"] = dict(env)
        r = self._req("POST", f"/v1/sandboxes/{self.id}/exec",
                      json=body, timeout=timeout + 20)
        d = r.json()
        return ExecResult(d.get("stdout", ""), d.get("stderr", ""),
                          d.get("exit_code", -1), d.get("truncated", False))

    def host(self, port: int) -> str:
        """Public preview URL for any guest port (E2B get_host parity). With
        multi-port sandboxes every bound port is reachable at <port>-<id>."""
        u = self.url or ""
        if "://" in u:
            scheme, rest = u.split("://", 1)
            hostpart = rest.split("/", 1)[0]
            dot = hostpart.find(".")
            if dot > 0 and "-" in hostpart[:dot]:  # hostpart == <port>-<id>.<domain>
                domain = hostpart[dot + 1:]
                return f"{scheme}://{port}-{self.id}.{domain}"
        return f"{self._base}/preview/{self.id}/{port}/"

    def run_code(self, code: str, lang: str = "python") -> ExecResult:
        """Write a snippet to a workspace file and run it — the E2B-style convenience."""
        ext = {"python": "py", "node": "js", "bash": "sh"}.get(lang, "txt")
        runner = {"python": "python3", "node": "node", "bash": "bash"}.get(lang, "cat")
        # Workspace-relative path: the /files API roots at /workspace and exec's
        # cwd is /workspace, so a relative path is visible to both.
        name = f"_sf_{int(time.time()*1000)}.{ext}"
        self.files.write(name, code)
        return self.run(f"{runner} {name}")

    # ── files (directory-aware; paths are relative to the /workspace root) ────
    def upload(self, local: str, remote: str) -> None:
        """Upload a file or an entire directory. Paths are relative to the
        sandbox workspace (/workspace) — e.g. upload('./app', 'app')."""
        p = Path(local)
        remote = remote.lstrip("/")
        if p.is_dir():
            self._upload_tar(p, remote)
        else:
            self.files.write(remote, p.read_bytes())

    def _upload_tar(self, local_dir: Path, remote: str) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(local_dir), arcname=".")
        buf.seek(0)
        # Upload the tar into the workspace, then untar it there via exec (cwd is
        # /workspace, so the relative tar path and target dir both resolve).
        tmp = f"_sf_up_{int(time.time()*1000)}.tgz"
        self.files.write(tmp, buf.read())
        self.run(f"mkdir -p {remote} && tar -xzf {tmp} -C {remote} && rm -f {tmp}").check()

    def download(self, remote: str, local: str) -> None:
        """Download a file (to a local path) or a directory (unpacked into local)."""
        remote = remote.lstrip("/")
        if self.run(f"test -d {remote} && echo DIR || echo FILE").stdout.startswith("DIR"):
            tmp = f"_sf_dl_{int(time.time()*1000)}.tgz"
            self.run(f"tar -czf {tmp} -C {remote} .").check()
            r = self._req("GET", f"/v1/sandboxes/{self.id}/files?path={tmp}")
            self.run(f"rm -f {tmp}")
            with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as t:
                members = [m for m in t.getmembers()
                           if not (m.name.startswith("..") or os.path.isabs(m.name))]
                Path(local).mkdir(parents=True, exist_ok=True)
                t.extractall(local, members=members)
        else:
            Path(local).write_text(self.files.read(remote))

    # ── lifecycle ────────────────────────────────────────────────────────────
    def pause(self) -> None:
        self._req("POST", f"/v1/sandboxes/{self.id}/pause")

    def resume(self) -> None:
        self._req("POST", f"/v1/sandboxes/{self.id}/resume")

    def set_timeout(self, seconds: int) -> None:
        self._req("POST", f"/v1/sandboxes/{self.id}/timeout", json={"seconds": seconds})

    def logs(self) -> list:
        return self._req("GET", f"/v1/sandboxes/{self.id}/logs").json()

    def metrics(self) -> dict:
        return self._req("GET", f"/v1/sandboxes/{self.id}/metrics").json()

    def kill(self) -> None:
        try:
            self._s.delete(f"{self._base}/v1/sandboxes/{self.id}", timeout=30)
        except requests.RequestException:
            pass

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _req(self, method: str, path: str, timeout: int = 30, **kw) -> requests.Response:
        r = self._s.request(method, f"{self._base}{path}", timeout=timeout, **kw)
        if r.status_code == 404:
            raise RuntimeError(f"not found: {path}")
        if not r.ok:
            raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:200]}")
        return r

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *_):
        self.kill()

    def __repr__(self) -> str:
        return f"Sandbox(id={self.id!r}, template={self.template!r})"


def build_image(context_dir: str, tag: str, *,
                api_url: Optional[str] = None, api_key: Optional[str] = None) -> str:
    """Build a custom image from a local context (Dockerfile at its root) on the
    fleet and return the launchable tag:

        img = build_image("./myapp", "myapp")
        with Sandbox.create(image=img) as sb:
            ...
    """
    cfg = config()
    base = (api_url or cfg["api_url"]).rstrip("/")
    key = api_key or cfg["key"]
    if not base:
        raise RuntimeError("no API URL — set PILLDROPS_API_URL to your PillDrops server")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(context_dir, arcname=".")
    buf.seek(0)
    s = requests.Session()
    if key:
        s.headers["Authorization"] = f"Bearer {key}"
    r = s.post(f"{base}/v1/images/build", params={"name": tag}, data=buf.read(),
               headers={"Content-Type": "application/octet-stream"}, timeout=1500)
    if not r.ok:
        raise RuntimeError(f"image build request failed ({r.status_code}): {r.text[:300]}")
    d = r.json()
    if not d.get("ok"):
        raise RuntimeError("image build failed:\n" + (d.get("log") or "")[-2000:])
    return d["tag"]


class Templates:
    """List available templates."""

    def __init__(self, api_url: Optional[str] = None, api_key: Optional[str] = None):
        cfg = config()
        self._base = (api_url or cfg["api_url"]).rstrip("/")
        self._s = requests.Session()
        key = api_key or cfg["key"]
        if key:
            self._s.headers["Authorization"] = f"Bearer {key}"

    def list(self) -> list:
        return self._s.get(f"{self._base}/v1/templates", timeout=15).json()
