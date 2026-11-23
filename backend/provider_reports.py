import json
import os
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_json(url, token, *, key_header=False, extra_headers=None):
    headers = {"xi-api-key": token} if key_header else {"Authorization": "Bearer " + token}
    with urlopen(Request(url, headers={**headers, **(extra_headers or {})}), timeout=8) as response:
        return json.load(response)


def connection_status():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        return {"provider": "OpenAI", "status": "not configured"}
    started = monotonic()
    try:
        result = read_json("https://api.openai.com/v1/models", key)
        status = "reachable" if isinstance(result.get("data"), list) else "unexpected response"
    except (OSError, ValueError, AttributeError):
        status = "request failed"
    return {"provider": "OpenAI", "status": status, "latency_ms": round((monotonic() - started) * 1000)}


def openai_costs():
    key = os.environ.get("OPENAI_ADMIN_KEY", "").strip()
    if not key:
        return None
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    params = {"start_time": int(start.timestamp()), "end_time": int(now.timestamp()), "limit": 7}
    project = os.environ.get("OPENAI_COST_PROJECT_ID", "").strip()
    if project:
        params["project_ids"] = project
    totals = {}
    cursors = set()
    for _ in range(20):
        result = read_json("https://api.openai.com/v1/organization/costs?" + urlencode(params), key)
        for bucket in result["data"]:
            for item in bucket["results"]:
                amount = item["amount"]
                currency = amount["currency"].upper()
                value = Decimal(str(amount["value"]))
                if not value.is_finite():
                    raise ValueError("Invalid cost value.")
                totals[currency] = totals.get(currency, Decimal(0)) + value
        if not result["has_more"]:
            return {"scope": "project" if project else "organization", "start": start.isoformat(),
                    "end": now.isoformat(), "totals": {currency: str(total) for currency, total in totals.items()}}
        cursor = result["next_page"]
        if not cursor or cursor in cursors:
            raise ValueError("Invalid cost pagination.")
        cursors.add(cursor)
        params["page"] = cursor
    raise ValueError("Cost pagination exceeded the supported limit.")


def elevenlabs_subscription():
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        return {"provider": "ElevenLabs", "status": "not configured"}
    started = monotonic()
    report = {"provider": "ElevenLabs"}
    try:
        subscription = read_json("https://api.elevenlabs.io/v1/user/subscription", key, key_header=True)
        used, limit = subscription["character_count"], subscription["character_limit"]
        if any(type(count) is not int or count < 0 for count in (used, limit)):
            raise ValueError("Invalid character counts.")
        report.update(status="reachable", characters_used=used, character_limit=limit)
        overage = subscription.get("current_overage")
        if isinstance(overage, dict):
            amount = Decimal(str(overage.get("amount")))
            currency = overage.get("currency")
            if amount.is_finite() and isinstance(currency, str) and len(currency) == 3 and currency.isalpha():
                report["current_overage"] = {"amount": str(amount), "currency": currency.upper()}
    except (OSError, KeyError, TypeError, ValueError):
        report["status"] = "request failed"
    except InvalidOperation:
        # Invalid optional overage data does not invalidate the quota.
        pass
    return {**report, "latency_ms": round((monotonic() - started) * 1000)}



def media_account(provider):
    settings = {
        "runway": ("Runway", "RUNWAY_API_KEY"),
        "muse": ("Muse Video", "MUSE_API_KEY"),
        "vertex": ("Vertex AI", "VERTEX_ACCESS_TOKEN"),
    }
    name, key_name = settings[provider]
    key = os.environ.get(key_name, "").strip()
    if provider == "vertex" and not key:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
        from google_auth import access_token
        key = access_token()
    report = {"provider": name, "status": "not configured"}
    if not key:
        return report

    headers = {}
    if provider == "runway":
        url = "https://api.dev.runwayml.com/v1/organization"
        headers = {"X-Runway-Version": "2024-11-06"}
    elif provider == "muse":
        task = os.environ.get("MUSE_HEALTH_TASK_ID", "").strip()
        if not task:
            return {**report, "status": "set an existing task ID to check"}
        url = "https://muse-video.com/api/v1/status?" + urlencode({"task_id": task})
    else:
        region = os.environ.get("VERTEX_REGION", "").strip()
        model = os.environ.get("IMAGE_MODEL", "").strip()
        if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", item) for item in (region, model)):
            return {**report, "status": "set a Vertex region and Imagen model"}
        url = f"https://{region}-aiplatform.googleapis.com/v1/publishers/google/models/{model}"

    started = monotonic()
    try:
        result = read_json(url, key, extra_headers=headers) if headers else read_json(url, key)
        if provider == "runway":
            balance = result["creditBalance"]
            if type(balance) is not int:
                raise ValueError("Invalid credit balance.")
            report["credit_balance"] = balance
        elif provider == "muse":
            task_data = result["data"]
            if result.get("code") != 200 or task_data.get("task_id") != task:
                raise ValueError("Unexpected task response.")
            state = task_data["status"]
            if state not in {"IN_PROGRESS", "SUCCESS", "FAILED"}:
                raise ValueError("Unexpected task state.")
            report["task_status"] = state
            credits = task_data.get("consumed_credits")
            if type(credits) is int and credits >= 0:
                report["task_credits"] = credits
        elif not isinstance(result["name"], str) or not result["name"]:
            raise ValueError("Unexpected publisher model.")
        report["status"] = "reachable"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report["status"] = "request failed"
    return {**report, "latency_ms": round((monotonic() - started) * 1000)}


def runway_usage():
    key = os.environ.get("RUNWAY_API_KEY", "").strip()
    if not key:
        return None
    end = datetime.now(UTC).date() + timedelta(days=1)
    start = end - timedelta(days=7)
    query = urlencode({"startDate": start.isoformat(), "beforeDate": end.isoformat()})
    result = read_json("https://api.dev.runwayml.com/v1/organization/usage?" + query,
                       key, extra_headers={"X-Runway-Version": "2024-11-06"})
    models = {}
    for day in result["results"]:
        for entry in day["usedCredits"]:
            amount, model = entry["amount"], entry["model"]
            if type(amount) is not int or not isinstance(model, str) or not model:
                raise ValueError("Invalid Runway usage response.")
            models[model] = models.get(model, 0) + amount
    return {"start": start.isoformat(), "end_exclusive": end.isoformat(),
            "credits_used": sum(models.values()), "by_model": models}
