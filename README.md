# PillDrops Python SDK

The Python client for [PillDrops](https://github.com/pilldrops-oss/pilldrops), a
self-hosted engine that runs untrusted code in isolated microVMs. Create a
sandbox, run commands and code in it, move files, start a server and get its
preview URL, pause and resume it.

```bash
pip install pilldrops
```

## Point it at your server

```bash
export PILLDROPS_API_URL=http://localhost:8080          # your PillDrops server
export PILLDROPS_API_KEY=$(cat /var/lib/sandboxd/bootstrap.key)
```

Settings resolve from explicit arguments, then `PILLDROPS_API_URL` /
`PILLDROPS_API_KEY` (`E2B_*`, `SANDFORGE_*` and `SANDBOX_*` are read as
fallbacks, so code written for the E2B SDK runs unchanged), then
`~/.sandforge/config.json`. There is no built-in server: set one.

## Use it

```python
from pilldrops import Sandbox

with Sandbox.create(template="python-3.11") as sb:          # destroyed on exit
    print(sb.run("python3 -c 'print(6*7)'").stdout)          # 42
    sb.files.write("app/main.py", "print('hello')")           # relative to the sandbox home
    print(sb.run("python3 app/main.py").stdout)              # hello
    sb.upload("./project", "/project")                       # a whole directory
    sb.pause()
    sb.resume()                                              # same memory, same processes

# A server, reachable at a preview URL
app = Sandbox.create(template="python-3.11", start="python3 -m http.server 8080", ports=[8080])
print(app.url)
app.kill()
```

| | |
|---|---|
| `Sandbox.create(template, *, image, start, ports, env, vcpu, mem_mb, storage_mb, timeout)` | a new sandbox |
| `Sandbox.connect(id)` · `Sandbox.list()` | an existing one · all of them |
| `sb.run(cmd, cwd, timeout, env)` · `sb.run_code(code, lang)` | `ExecResult` with `stdout`, `stderr`, `exit_code`, `.ok`, `.check()` |
| `sb.files.write/read/list` · `sb.upload` · `sb.download` | files and directories |
| `sb.url` · `sb.host(port)` | preview URLs |
| `sb.pause()` · `sb.resume()` · `sb.set_timeout(s)` · `sb.kill()` | lifecycle |
| `sb.logs()` · `sb.metrics()` | observability |
| `build_image(context_dir, tag)` | build a custom image from a Dockerfile; launch it with `Sandbox.create(image=…)` |

## Webhooks

Get a signed POST when a sandbox in your org changes state. These take the org
API key.

```python
from pilldrops import Webhooks, verify_webhook_signature

hooks = Webhooks()
created = hooks.create("https://example.com/hook", ["sandbox.ended"])
secret = created["secret"]                                   # store it now: returned only here

# in your endpoint, with the raw request body
ok = verify_webhook_signature(secret, headers["x-pilldrops-timestamp"],
                              headers["x-pilldrops-signature"], raw_body)
```

| | |
|---|---|
| `hooks.list()` · `hooks.create(url, events)` · `hooks.delete(id)` | manage endpoints |
| `hooks.test(id)` | send one signed probe: `{"ok", "status", "error"}` |
| `hooks.set_enabled(id, enabled)` | pause or resume deliveries |
| `hooks.deliveries()` | recent deliveries, newest first |
| `verify_webhook_signature(secret, timestamp, signature, body, tolerance=300)` | `True` when the signature matches and the timestamp is fresh |

Events: `sandbox.created`, `sandbox.ended`, `sandbox.paused`, `sandbox.resumed`,
`sandbox.checkpointed`, `sandbox.forked`, `sandbox.restarted`, `sandbox.crashed`,
`sandbox.out_of_memory`, `sandbox.unreachable`. The body is
`{"id", "type", "at", "sandbox": {"id", "template"}, "data"}`. Retries reuse
`id` (also in `x-pilldrops-delivery`), so dedupe on it.

`import sandforge` and `import yoursandbox` still work: they ship in this
package as aliases of its earlier names.

## Tests

```bash
python3 -m pytest tests            # unit tests; the integration test skips without a server
```

## License

[MIT](LICENSE).
