"""GitHub via the `gh` CLI: issues, branches, pull requests."""
from __future__ import annotations

from pathlib import Path

from ..ingest.common import run


def create_issue(repo_dir: Path, title: str, body: str, labels: list[str] | None = None) -> str:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels or []:
        cmd += ["--label", label]
    out = run(cmd, cwd=repo_dir, timeout=60, check=False)
    if "http" not in out:  # label may not exist; retry without labels
        out = run(["gh", "issue", "create", "--title", title, "--body", body], cwd=repo_dir, timeout=60)
    return out.strip()


def create_branch(repo_dir: Path, name: str, base: str | None = None) -> None:
    run(["git", "-C", str(repo_dir), "checkout", "-q", base or "-"], check=False)
    run(["git", "-C", str(repo_dir), "checkout", "-q", "-B", name])


def commit_all(repo_dir: Path, message: str) -> bool:
    run(["git", "-C", str(repo_dir), "add", "-A"])
    status = run(["git", "-C", str(repo_dir), "status", "--porcelain"])
    if not status.strip():
        return False
    run(["git", "-C", str(repo_dir), "-c", "user.name=AI CEO", "-c", "user.email=ai-ceo@localhost",
         "commit", "-q", "-m", message])
    return True


def push_and_pr(repo_dir: Path, branch: str, title: str, body: str, draft: bool = True) -> str:
    run(["git", "-C", str(repo_dir), "push", "-u", "origin", branch, "--force-with-lease"], timeout=300)
    cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch]
    if draft:
        cmd.append("--draft")
    return run(cmd, cwd=repo_dir, timeout=60).strip()


def has_github_remote(repo_dir: Path) -> bool:
    out = run(["git", "-C", str(repo_dir), "remote", "get-url", "origin"], check=False)
    return "github.com" in out


def default_branch(repo_dir: Path) -> str:
    out = run(["git", "-C", str(repo_dir), "symbolic-ref", "refs/remotes/origin/HEAD"], check=False).strip()
    return out.rsplit("/", 1)[-1] if out else "main"
