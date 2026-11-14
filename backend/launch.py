"""Start the Windows studio and supervise its three local services."""
import os
import secrets
import socket
import shutil
import subprocess
import sys
import time
import webbrowser
from urllib.error import URLError
from urllib.request import urlopen

from backend.environment import ROOT, load_env

def available_port(preferred):
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", preferred))
        except OSError:
            listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def run(command, *, check=True):
    return subprocess.run(command, cwd=ROOT, check=check)


def wait_ready(url, processes):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A studio process stopped. Check the terminal output.")
        try:
            with urlopen(url, timeout=1):
                return
        except (URLError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError(f"Startup timed out for {url}.")


def main():
    load_env()
    npm = shutil.which("npm.cmd")
    if not npm:
        raise RuntimeError("Install Node.js and reopen PowerShell.")
    token = os.environ.get("STUDIO_ADMIN_TOKEN", "")
    if not token:
        token = secrets.token_urlsafe(32)
        os.environ["STUDIO_ADMIN_TOKEN"] = token
    if len(token) < 24:
        raise RuntimeError("STUDIO_ADMIN_TOKEN must have at least 24 characters.")
    api_port = available_port(int(os.environ.get("STUDIO_API_PORT", "8765")))
    studio_port = available_port(int(os.environ.get("STUDIO_PORT", "3000")))
    while studio_port == api_port:
        studio_port = available_port(0)
    api_url = f"http://127.0.0.1:{api_port}"
    studio_url = f"http://127.0.0.1:{studio_port}"
    os.environ["STUDIO_API_URL"] = api_url
    if run([sys.executable, "-c", "import fastapi, uvicorn, pydantic"], check=False).returncode:
        run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    if not (ROOT / "node_modules" / "next" / "package.json").is_file():
        run([npm, "ci", "--no-audit", "--no-fund"])
    run([npm, "run", "build"])
    processes = []
    try:
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(api_port)], cwd=ROOT))
        wait_ready(api_url + "/health", processes)
        processes.append(subprocess.Popen([sys.executable, "-m", "backend.worker"], cwd=ROOT))
        processes.append(subprocess.Popen(
            ["node", str(ROOT / "node_modules" / "next" / "dist" / "bin" / "next"),
             "start", "--hostname", "127.0.0.1", "--port", str(studio_port)], cwd=ROOT))
        wait_ready(studio_url, processes)
        print(f"Studio: {studio_url}\nAdmin token: {token}\nKeep this terminal open. Press Ctrl+C to stop.", flush=True)
        if os.environ.get("STUDIO_NO_BROWSER") != "1":
            webbrowser.open(studio_url)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise RuntimeError("A studio service stopped. Check its terminal output.")
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Studio startup failed: {exc}")
