from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def request(method: str, url: str, *, headers: dict[str, str] | None = None, json_body: Any = None,
            form: dict[str, str] | None = None, basic_auth: tuple[str, str] | None = None, timeout: int = 60) -> Any:
    hdrs = {"User-Agent": "ai-ceo/0.1", **(headers or {})}
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    if basic_auth:
        token = base64.b64encode(f"{basic_auth[0]}:{basic_auth[1]}".encode()).decode()
        hdrs["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url} -> {exc.code}: {exc.read().decode()[:500]}") from exc
    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return body
