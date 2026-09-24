"""Generic outbound webhook (Zapier / Make / n8n). The receiving automation decides where the payload
goes: X, LinkedIn, Mastodon, newsletter, Slack. This is how channels without a simple API get covered."""
from __future__ import annotations

from .http import request


def send(url: str, event: str, payload: dict) -> str:
    request("POST", url, json_body={"event": event, **payload})
    return f"webhook delivered: {event}"
