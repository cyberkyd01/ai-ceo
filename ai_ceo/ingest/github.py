"""Clone a GitHub repository and gather raw facts. The CEO turns the facts into a ProductDossier."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import detect_stack, file_tree, find_readme, key_manifests, run

GITHUB_RE = re.compile(r"^(?:https?://github\.com/|git@github\.com:)([^/]+)/([^/\s]+?)(?:\.git)?/?$")


def is_github_url(source: str) -> bool:
    return bool(GITHUB_RE.match(source.strip()))


def parse_repo(source: str) -> tuple[str, str]:
    m = GITHUB_RE.match(source.strip())
    if not m:
        raise ValueError(f"not a GitHub URL: {source}")
    return m.group(1), m.group(2)


def repo_stats(owner: str, name: str) -> dict:
    """Public repo metadata via the gh CLI (already authenticated on the machine)."""
    try:
        raw = run(["gh", "api", f"repos/{owner}/{name}"], timeout=60)
        data = json.loads(raw)
        stats = {
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "watchers": data.get("subscribers_count", 0),
        }
        meta = {
            "description": data.get("description") or "",
            "homepage": data.get("homepage") or "",
            "topics": data.get("topics") or [],
            "license": (data.get("license") or {}).get("spdx_id") or "",
            "default_branch": data.get("default_branch") or "main",
            "pushed_at": data.get("pushed_at") or "",
        }
        try:  # traffic needs push access; ignore if not permitted
            views = json.loads(run(["gh", "api", f"repos/{owner}/{name}/traffic/views"], timeout=60))
            stats["views_14d"] = views.get("count", 0)
            stats["unique_visitors_14d"] = views.get("uniques", 0)
        except RuntimeError:
            pass
        return {"stats": stats, "meta": meta}
    except (RuntimeError, json.JSONDecodeError) as exc:
        return {"stats": {}, "meta": {}, "error": str(exc)}


def clone_or_update(source: str, dest: Path) -> None:
    if (dest / ".git").exists():
        run(["git", "-C", str(dest), "fetch", "--all", "--prune"], timeout=300)
        run(["git", "-C", str(dest), "pull", "--ff-only"], timeout=300, check=False)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "50", source, str(dest)], timeout=600)


def ingest_github(source: str, repo_dir: Path) -> dict:
    owner, name = parse_repo(source)
    clone_or_update(source, repo_dir)
    info = repo_stats(owner, name)
    log = run(["git", "-C", str(repo_dir), "log", "--oneline", "-n", "30"], check=False)
    return {
        "source": source,
        "owner": owner,
        "repo": name,
        "readme": find_readme(repo_dir),
        "manifests": key_manifests(repo_dir),
        "stack": detect_stack(repo_dir),
        "file_tree": file_tree(repo_dir),
        "recent_commits": log,
        **info,
    }
