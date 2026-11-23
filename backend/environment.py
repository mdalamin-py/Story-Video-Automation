import os
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"          # tests point this at a temporary file
FILE_KEYS = "STUDIO_ENV_FILE_KEYS"   # names that came from .env, not from the system environment
_write_lock = threading.Lock()


def file_keys():
    return {name for name in os.environ.get(FILE_KEYS, "").split(",") if name}


def _remember(names):
    os.environ[FILE_KEYS] = ",".join(sorted(file_keys() | set(names)))


def load_env():
    path = ROOT / ".env"
    if not path.is_file():
        return
    loaded = []
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        key, separator, value = entry.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key.isidentifier():
            raise ValueError(f"Invalid .env assignment on line {number}.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    _remember(loaded)


def fresh_env():
    """.env as it is now, for the next job. A blank line in .env clears only a key that .env itself
    supplied: it never hides a key set in the Windows environment (for example a fresh .env made
    from .env.example, full of empty KEY= lines)."""
    supplied = file_keys()
    return {key: value for key, value in env_file_values().items()
            if value or key in supplied or key not in os.environ}


def env_file_values():
    """The current values in .env, read fresh, so keys connected on the dashboard apply to the next job
    without restarting the studio."""
    path = ENV_FILE
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key.strip().isidentifier() and not line.lstrip().startswith("#"):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[key.strip()] = value
    return values


def update_env_file(updates):
    """Set or clear keys in .env in place, keeping every other line and comment as it was.
    A new .env starts from .env.example so the remaining settings stay documented.
    Saves from two dashboard requests at once are serialized so neither loses the other's key."""
    with _write_lock:
        _update_env_file(updates)
    for key, value in updates.items():
        os.environ[key] = value
    _remember(updates)


def _update_env_file(updates):
    path = ENV_FILE
    if path.is_file():
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    elif (ROOT / ".env.example").is_file() and path == ROOT / ".env":
        lines = (ROOT / ".env.example").read_text(encoding="utf-8-sig").splitlines()
    else:
        lines = []
    pending = dict(updates)
    output = []
    for line in lines:
        key = line.strip().partition("=")[0].strip()
        if not line.lstrip().startswith("#") and "=" in line and key in updates:
            if key in pending:
                output.append(f"{key}={pending.pop(key)}")
            continue                                   # drop duplicate assignments of the same key
        output.append(line)
    output += [f"{key}={value}" for key, value in pending.items()]
    handle, temporary = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write("\n".join(output) + "\n")
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:          # Windows: a job is reading .env this instant
                if attempt == 9:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
