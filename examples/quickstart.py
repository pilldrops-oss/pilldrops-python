"""PillDrops Python SDK quickstart.

Prereq: set PILLDROPS_API_URL and PILLDROPS_API_KEY to your PillDrops server.

    python quickstart.py
"""
from pilldrops import Sandbox


def main():
    # 1) Run code in an ephemeral sandbox.
    with Sandbox.create(template="python-3.11") as sb:
        print("run:", sb.run("python3 -c 'print(6*7)'").stdout.strip())
        print("run_code:", sb.run_code("import sys; print(sys.version.split()[0])").stdout.strip())

        # Push a local directory and run it.
        # sb.upload("./myproject", "/app")
        # print(sb.run("cd /app && python main.py").stdout)

    # 2) Launch an app server and get a public preview URL.
    app = Sandbox.create(template="python-3.11",
                         start="python3 -m http.server 8080", ports=[8080])
    print("app preview URL:", app.url)
    # ... hit app.url from your browser or agent; then:
    app.kill()


if __name__ == "__main__":
    main()
