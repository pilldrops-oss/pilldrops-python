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
    sb.files.write("/app/main.py", "print('hello')")
    print(sb.run("python3 main.py", cwd="/app").stdout)      # hello
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

`import sandforge` and `import yoursandbox` still work: they ship in this
package as aliases of its earlier names.

## Tests

```bash
python3 -m pytest tests            # unit tests; the integration test skips without a server
```

## License

[MIT](LICENSE).
