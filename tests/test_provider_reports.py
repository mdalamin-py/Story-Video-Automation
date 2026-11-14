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


def test_elevenlabs_exposes_quota_and_overage_only(monkeypatch):
    from backend.provider_reports import elevenlabs_subscription

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    payload = {"character_count": 50, "character_limit": 100,
               "current_overage": {"amount": "1.25", "currency": "usd"},
               "open_invoices": [{"private": True}]}
    with patch("backend.provider_reports.read_json", return_value=payload) as read:
        result = elevenlabs_subscription()
    read.assert_called_once_with("https://api.elevenlabs.io/v1/user/subscription", "test", key_header=True)
    assert result["status"] == "reachable"
    assert result["characters_used"] == 50
    assert result["current_overage"] == {"amount": "1.25", "currency": "USD"}
    assert "open_invoices" not in result
