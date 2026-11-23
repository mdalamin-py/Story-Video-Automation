"""Google sign-in for Vertex AI without pasting tokens that expire every hour.

"Sign in with Google" on the Providers page runs the Google Cloud CLI's own sign-in
(`gcloud auth application-default login`), which opens Google's page in the browser. Google keeps
the sign-in on this PC; each request then gets a fresh access token from it. A VERTEX_ACCESS_TOKEN
in .env still works and takes priority."""
import os
import shutil
import subprocess
import time
from pathlib import Path

_cache = {"token": "", "until": 0.0}


def gcloud():
    found = shutil.which("gcloud")
    if found:
        return found
    if os.name == "nt":
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
            candidate = Path(base) / "Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
            if base and candidate.is_file():
                return str(candidate)
    return None


def _signed_in_token():
    cli = gcloud()
    if not cli:
        return ""
    if _cache["token"] and time.monotonic() < _cache["until"]:
        return _cache["token"]
    try:
        result = subprocess.run([cli, "auth", "application-default", "print-access-token"],
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    token = result.stdout.strip() if result.returncode == 0 else ""
    if token:
        _cache.update(token=token, until=time.monotonic() + 45 * 60)   # Google tokens last an hour
    return token


def access_token():
    """VERTEX_ACCESS_TOKEN from .env, otherwise a fresh token from the Google sign-in."""
    return os.environ.get("VERTEX_ACCESS_TOKEN", "").strip() or _signed_in_token()


def signed_in():
    return bool(_signed_in_token())


def start_sign_in():
    """Opens Google's sign-in page in the browser. Returns False when the Google Cloud CLI is missing."""
    cli = gcloud()
    if not cli:
        return False
    _cache.update(token="", until=0.0)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([cli, "auth", "application-default", "login", "--quiet"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return True
