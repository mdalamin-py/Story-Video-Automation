import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"          # tests point this at a temporary file


def load_env():
    path = ROOT / ".env"
    if not path.is_file():
        return
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
        os.environ.setdefault(key, value)


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
    A new .env starts from .env.example so the remaining settings stay documented."""
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
    temporary = path.with_name(".env.tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    temporary.replace(path)
    for key, value in updates.items():
        os.environ[key] = value
