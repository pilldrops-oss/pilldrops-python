"""SandForge — Python SDK for AI-native sandboxes.

    from sandforge import Sandbox

    with Sandbox.create(template="python-3.11") as sb:
        print(sb.run("python -c 'print(2+2)'").stdout)   # 4
        sb.upload("./app", "/app")                        # push a directory
        r = sb.run("cd /app && python main.py")

    # Run an app server and get a public preview URL:
    with Sandbox.create(template="node-20", start="npm run dev", ports=[3000]) as app:
        print(app.url)   # https://.../preview/<id>/3000/

Credentials + endpoint resolve from (in order): explicit args, SANDFORGE_API_URL/
SANDFORGE_API_KEY env (E2B_/SANDBOX_ accepted as fallbacks), then ~/.sandforge/config.json
(written by `sandforge login`).
"""
from .sandbox import (Sandbox, ExecResult, Templates, Webhooks, config, build_image,
                      verify_webhook_signature)

__all__ = ["Sandbox", "ExecResult", "Templates", "Webhooks", "config", "build_image",
           "verify_webhook_signature"]
__version__ = "1.1.1"
