"""Read-only revenue metrics from Stripe (balance transactions over the last 30 days)."""
from __future__ import annotations

import time

from .http import request


def revenue_last_30d(api_key: str) -> dict[str, float]:
    since = int(time.time()) - 30 * 86400
    data = request("GET", f"https://api.stripe.com/v1/balance_transactions?limit=100&type=charge&created[gte]={since}",
                   basic_auth=(api_key, ""))
    txs = data.get("data", []) if isinstance(data, dict) else []
    gross = sum(t.get("amount", 0) for t in txs) / 100
    net = sum(t.get("net", 0) for t in txs) / 100
    return {"revenue_30d_gross": gross, "revenue_30d_net": net, "charges_30d": float(len(txs))}
