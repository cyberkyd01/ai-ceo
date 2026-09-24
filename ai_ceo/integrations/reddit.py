"""Reddit posting with a 'script' app (password grant). Respect each subreddit's self-promotion rules;
the CEO prompt is told to prefer genuinely useful posts over ads."""
from __future__ import annotations

from .http import request


def _token(client_id: str, client_secret: str, username: str, password: str) -> str:
    data = request("POST", "https://www.reddit.com/api/v1/access_token", basic_auth=(client_id, client_secret),
                   form={"grant_type": "password", "username": username, "password": password},
                   headers={"User-Agent": f"ai-ceo/0.1 by {username}"})
    if "access_token" not in data:
        raise RuntimeError(f"reddit auth failed: {data}")
    return data["access_token"]


def submit_post(creds: dict[str, str], subreddit: str, title: str, text: str | None = None, url: str | None = None) -> str:
    token = _token(creds["reddit_client_id"], creds["reddit_client_secret"], creds["reddit_username"], creds["reddit_password"])
    form = {"sr": subreddit, "title": title, "api_type": "json", "kind": "link" if url else "self"}
    if url:
        form["url"] = url
    else:
        form["text"] = text or ""
    data = request("POST", "https://oauth.reddit.com/api/submit", form=form,
                   headers={"Authorization": f"bearer {token}", "User-Agent": f"ai-ceo/0.1 by {creds['reddit_username']}"})
    errors = (data.get("json") or {}).get("errors") if isinstance(data, dict) else None
    if errors:
        raise RuntimeError(f"reddit rejected post: {errors}")
    link = ((data.get("json") or {}).get("data") or {}).get("url", "") if isinstance(data, dict) else ""
    return f"reddit post submitted to r/{subreddit}: {link}"
