import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_json(url, token, *, key_header=False):
    headers = {"xi-api-key": token} if key_header else {"Authorization": "Bearer " + token}
    with urlopen(Request(url, headers=headers), timeout=8) as response:
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
