import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import monotonic
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def read_json(url, token):
    with urlopen(Request(url, headers={"Authorization": "Bearer " + token}), timeout=8) as response:
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
