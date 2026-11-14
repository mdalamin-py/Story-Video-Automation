import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
