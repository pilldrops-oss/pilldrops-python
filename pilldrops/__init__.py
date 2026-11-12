"""PillDrops — Python SDK for AI-native sandboxes (pilldrops.com).

    from pilldrops import Sandbox

    with Sandbox.create(template="python-3.11") as sb:
        print(sb.run("python -c 'print(2+2)'").stdout)   # 4
        sb.upload("./app", "/app")                        # push a directory
        r = sb.run("cd /app && python main.py")

    # Run an app server and get a public preview URL:
    with Sandbox.create(template="node-20", start="npm run dev", ports=[3000]) as app:
        print(app.url)   # https://.../preview/<id>/3000/

Credentials + endpoint resolve from (in order): explicit args, PILLDROPS_API_URL/
PILLDROPS_API_KEY env (SANDFORGE_/E2B_/SANDBOX_ accepted as fallbacks), then
~/.sandforge/config.json (written by `pilldrops login`).

`import sandforge` and `import yoursandbox` keep working — they ship in the same
distribution as compatibility aliases of this package.
"""
from sandforge.sandbox import Sandbox, ExecResult, Templates, config, build_image

__all__ = ["Sandbox", "ExecResult", "Templates", "config", "build_image"]
__version__ = "1.1.1"
