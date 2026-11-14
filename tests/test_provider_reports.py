from unittest.mock import patch

from backend.provider_reports import connection_status, openai_costs


def test_connection_status_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert connection_status()["status"] == "not configured"


def test_connection_status_uses_read_only_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    with patch("backend.provider_reports.read_json", return_value={"data": []}) as read:
        assert connection_status()["status"] == "reachable"
        read.assert_called_once_with("https://api.openai.com/v1/models", "test")


def test_openai_cost_totals_across_pages(monkeypatch):
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "test")
    monkeypatch.setenv("OPENAI_COST_PROJECT_ID", "project")
    pages = [
        {"data": [{"results": [{"amount": {"currency": "usd", "value": "0.1"}}]}],
         "has_more": True, "next_page": "second"},
        {"data": [{"results": [{"amount": {"currency": "usd", "value": "0.2"}}]}],
         "has_more": False},
    ]
    with patch("backend.provider_reports.read_json", side_effect=pages) as read:
        result = openai_costs()
    assert result["totals"] == {"USD": "0.3"}
    assert result["scope"] == "project"
    assert "page=second" in read.call_args.args[0]
