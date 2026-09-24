"""Engineering: writes feature specs that close competitor gaps, files them as issues, and (when a coder
is configured) implements them on a branch and opens a draft pull request.

The coder is Claude Code in headless mode (`claude -p`). It runs inside the cloned repo with edit
permissions limited to that folder; the branch/commit/PR steps are done here, not by the coder."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ..config import Settings
from ..context import CEO_IDENTITY, Context
from ..integrations import github as gh
from ..llm import LLM
from ..schemas import FeatureSpec

SYSTEM = CEO_IDENTITY + """

Task: write a feature specification a competent engineer (or coding agent) can implement without
asking questions. Tie it to the strategy: which differentiator or competitor gap does it serve?
Keep scope small enough to ship in one pull request; split otherwise and describe only the first slice."""

CODER_PROMPT = """You are implementing one feature in this repository on a dedicated git branch.
Do not commit, push, or change branches; the orchestrator handles git. Do not modify CI secrets or
deployment configuration. Follow the repository's existing conventions and add or update tests where
the project has them. When done, write a short summary of what changed to AI_CEO_SUMMARY.md at the repo root.

# Feature spec
Title: {title}

Problem: {problem}

Proposed solution: {solution}

Acceptance criteria:
{criteria}

Out of scope:
{out_of_scope}
"""


def write_spec(llm: LLM, ctx: Context, brief: str) -> FeatureSpec:
    user = f"{ctx.company_block()}\n\n## Feature brief from the CEO\n{brief}\n\nProduce the FeatureSpec."
    return llm.structured("engineering.spec", SYSTEM, user, FeatureSpec)


def spec_markdown(spec: FeatureSpec) -> str:
    return "\n".join([
        f"## Problem\n{spec.problem}", f"\n## Proposed solution\n{spec.proposed_solution}",
        "\n## Acceptance criteria", *[f"- [ ] {c}" for c in spec.acceptance_criteria],
        "\n## Out of scope", *[f"- {o}" for o in spec.out_of_scope],
        f"\n_Competitor reference: {spec.competitor_reference}. Effort: {spec.effort}._",
        "\n_Filed by AI CEO._",
    ])


def file_issue(repo_dir: Path, spec: FeatureSpec) -> str:
    return gh.create_issue(repo_dir, spec.title, spec_markdown(spec), labels=["ai-ceo", "enhancement"])


def coder_available(settings: Settings) -> bool:
    return settings.coder == "claude" and shutil.which("claude") is not None


def implement(settings: Settings, repo_dir: Path, spec: FeatureSpec, issue_url: str | None = None) -> str:
    if not coder_available(settings):
        raise RuntimeError("no coder available: install Claude Code (`claude`) or set AI_CEO_CODER=none")
    base = gh.default_branch(repo_dir)
    slug = re.sub(r"[^a-z0-9]+", "-", spec.title.lower()).strip("-")[:40]
    branch = f"ai-ceo/{slug}"
    gh.create_branch(repo_dir, branch, base=base)
    prompt = CODER_PROMPT.format(
        title=spec.title, problem=spec.problem, solution=spec.proposed_solution,
        criteria="\n".join(f"- {c}" for c in spec.acceptance_criteria),
        out_of_scope="\n".join(f"- {o}" for o in spec.out_of_scope) or "- (none)",
    )
    cmd = ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--max-turns", str(settings.coder_max_turns),
           "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash(git diff *),Bash(git status *),Bash(npm *),Bash(pnpm *),"
           "Bash(yarn *),Bash(pytest *),Bash(python *),Bash(go *),Bash(cargo *),Bash(make *),Bash(ls *)"]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"coder exited {proc.returncode}: {proc.stderr[-2000:]}")
    summary_path = repo_dir / "AI_CEO_SUMMARY.md"
    summary = summary_path.read_text() if summary_path.exists() else proc.stdout[-3000:]
    if summary_path.exists():
        summary_path.unlink()
    if not gh.commit_all(repo_dir, f"{spec.title}\n\nImplemented by AI CEO.\n"):
        raise RuntimeError("coder finished but made no changes")
    body = spec_markdown(spec) + "\n\n## Coder summary\n" + summary
    if issue_url:
        body += f"\n\nCloses {issue_url}"
    return gh.push_and_pr(repo_dir, branch, spec.title, body, draft=True)
