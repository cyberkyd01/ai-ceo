"""dev.to articles API. https://developers.forem.com/api"""
from __future__ import annotations

from .http import request


def publish_article(api_key: str, title: str, body_markdown: str, tags: list[str], published: bool = True,
                    canonical_url: str | None = None) -> str:
    article = {"title": title, "body_markdown": body_markdown, "published": published, "tags": tags[:4]}
    if canonical_url:
        article["canonical_url"] = canonical_url
    data = request("POST", "https://dev.to/api/articles", headers={"api-key": api_key}, json_body={"article": article})
    return f"dev.to article created: {data.get('url', data)}"
