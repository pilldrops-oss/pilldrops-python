"""Run a Playwright test suite in a sandbox and pull back the HTML report.

Uses a bring-your-own image (the official Playwright image ships the browsers),
so nothing needs to be pre-built on the platform. Every call here is covered by
the SDK test-suite; this ties them into the end-to-end flow.

    export PILLDROPS_API_URL=... PILLDROPS_API_KEY=...
    python playwright_report.py ./my-e2e-tests ./report
"""
import sys
from pilldrops import Sandbox

PLAYWRIGHT_IMAGE = "mcr.microsoft.com/playwright:v1.40.0-jammy"


def main(tests_dir: str, out_dir: str):
    # A bare custom image (no ports) is a keep-alive sandbox we exec into.
    with Sandbox.create(image=PLAYWRIGHT_IMAGE, vcpu=2, mem_mb=2048, timeout=1200) as sb:
        sb.upload(tests_dir, "e2e")                                    # push the project
        sb.run("cd e2e && (npm ci || npm install)", timeout=300).check()
        res = sb.run("cd e2e && npx playwright test --reporter=html", timeout=900)
        print(res.stdout[-2000:])
        print("suite exit:", res.exit_code)

        # The HTML report is a directory — download() unpacks it locally.
        sb.download("e2e/playwright-report", out_dir)
        print(f"report written to {out_dir}/  (open {out_dir}/index.html)")


if __name__ == "__main__":
    tests = sys.argv[1] if len(sys.argv) > 1 else "./e2e"
    out = sys.argv[2] if len(sys.argv) > 2 else "./report"
    main(tests, out)
