import json
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import connections, environment

TOKEN = "t" * 32


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import app
    monkeypatch.setenv("STUDIO_ADMIN_TOKEN", TOKEN)
    for name in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VERTEX_ACCESS_TOKEN", "VERTEX_PROJECT"):
        monkeypatch.setenv(name, "")             # saving sets os.environ; this restores it after each test
    monkeypatch.setattr("google_auth.gcloud", lambda: None)
    return TestClient(app, headers={"Authorization": "Bearer " + TOKEN})


def test_env_file_updates_keep_other_lines(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# my notes\nOPENAI_API_KEY=old\nOTHER=1\nOPENAI_API_KEY=dupe\n", encoding="utf-8")
    monkeypatch.setattr(environment, "ENV_FILE", env)
    monkeypatch.setenv("OPENAI_API_KEY", ""); monkeypatch.setenv("GEMINI_API_KEY", "")
    environment.update_env_file({"OPENAI_API_KEY": "sk-new-12345678", "GEMINI_API_KEY": "AIza-new-123"})
    assert env.read_text(encoding="utf-8") == "# my notes\nOPENAI_API_KEY=sk-new-12345678\nOTHER=1\nGEMINI_API_KEY=AIza-new-123\n"
    assert environment.env_file_values()["GEMINI_API_KEY"] == "AIza-new-123"


def test_a_tested_key_is_saved_and_never_sent_back(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(connections, "_read", lambda url, headers: seen.update(url=url, headers=headers) or {})
    reply = client.put("/api/connections/claude", json={"values": {"ANTHROPIC_API_KEY": "sk-ant-secret-9f3a"}})
    assert reply.json() == {"saved": True, "message": "Connected."}
    assert seen["url"].startswith("https://api.anthropic.com/") and seen["headers"]["x-api-key"] == "sk-ant-secret-9f3a"
    assert "ANTHROPIC_API_KEY=sk-ant-secret-9f3a" in environment.ENV_FILE.read_text(encoding="utf-8")
    listing = client.get("/api/connections")
    assert "sk-ant-secret" not in listing.text
    claude = next(s for s in listing.json()["services"] if s["id"] == "claude")
    assert claude["connected"] and claude["fields"][0]["saved"] == "•••• 9f3a"
    assert "Claude.ai" in claude["note"]


def test_a_refused_key_is_not_saved(client, monkeypatch):
    def refuse(url, headers):
        raise HTTPError(url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(connections, "_read", refuse)
    reply = client.put("/api/connections/gemini", json={"values": {"GEMINI_API_KEY": "AIza-wrong-key"}})
    assert reply.json()["saved"] is False and "refused" in reply.json()["message"]
    assert not environment.ENV_FILE.exists()


def test_bad_input_and_unknown_services_are_rejected(client):
    assert client.put("/api/connections/gemini", json={"values": {"GEMINI_API_KEY": "has space in it"}}).status_code == 422
    assert client.put("/api/connections/nope", json={"values": {}}).status_code == 404
    assert client.get("/api/connections", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_disconnect_clears_the_key(client, monkeypatch):
    monkeypatch.setattr(connections, "_read", lambda url, headers: {})
    client.put("/api/connections/openai", json={"values": {"OPENAI_API_KEY": "sk-proj-abcdefgh"}})
    assert client.delete("/api/connections/openai").json()["saved"] is True
    assert "OPENAI_API_KEY=\n" in environment.ENV_FILE.read_text(encoding="utf-8")


def test_google_sign_in_explains_the_missing_cloud_cli(client):
    reply = client.post("/api/connections/google/sign-in")
    assert reply.status_code == 409 and "Google Cloud CLI" in reply.json()["detail"]


def test_vertex_uses_the_google_sign_in_token(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import google_auth
    monkeypatch.delenv("VERTEX_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(google_auth, "_signed_in_token", lambda: "ya29.fresh")
    assert google_auth.access_token() == "ya29.fresh"
    monkeypatch.setenv("VERTEX_ACCESS_TOKEN", "ya29.pasted")
    assert google_auth.access_token() == "ya29.pasted"


def test_blank_env_lines_never_hide_system_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=\nGEMINI_API_KEY=\nRUNWAY_API_KEY=rw-from-file\n", encoding="utf-8")
    monkeypatch.setattr(environment, "ENV_FILE", env)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-windows")     # set in the system, not in .env
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-old")             # came from .env, then disconnected
    monkeypatch.setenv(environment.FILE_KEYS, "GEMINI_API_KEY")
    fresh = environment.fresh_env()
    assert "OPENAI_API_KEY" not in fresh
    assert fresh["GEMINI_API_KEY"] == "" and fresh["RUNWAY_API_KEY"] == "rw-from-file"


def test_parallel_saves_keep_every_key(tmp_path, monkeypatch):
    import threading
    env = tmp_path / ".env"
    monkeypatch.setattr(environment, "ENV_FILE", env)
    names = [f"KEY_{n}" for n in range(12)]
    for name in names:
        monkeypatch.setenv(name, "")
    threads = [threading.Thread(target=environment.update_env_file, args=({name: "value-" + name},)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    values = environment.env_file_values()
    assert all(values[name] == "value-" + name for name in names)
    assert not list(tmp_path.glob(".env.*.tmp"))
