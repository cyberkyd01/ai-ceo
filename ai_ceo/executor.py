"""Runs actions. Every action goes through two steps:

  prepare  - all the thinking and writing (specs, posts, packets). Always allowed; results land in outputs/.
  perform  - the external side effect (post, PR, listing). Gated by policy; may wait in the approval queue.

Owner approval re-enters at `approve()`, which performs using the prepared material.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import policy
from .config import Settings
from .context import Context
from .departments import distribution, engineering, marketing
from .integrations import devto, github as gh, reddit, webhook
from .llm import LLM
from .schemas import Action, FeatureSpec
from .state import CompanyStore


class Executor:
    def __init__(self, store: CompanyStore, llm: LLM, settings: Settings, ctx: Context):
        self.store, self.llm, self.settings, self.ctx = store, llm, settings, ctx

    # ---------------------------------------------------------------- entry points
    def handle(self, action_id: int) -> str:
        row = self.store.action(action_id)
        action = self._to_action(row)
        try:
            note = self.prepare(action, action_id)
        except Exception as exc:  # noqa: BLE001 - one bad action must not stop the cycle
            self.store.set_action(action_id, "failed", f"prepare failed: {exc}")
            return f"failed: {exc}"
        action = self._to_action(self.store.action(action_id))  # payload may have grown
        if action.kind in ("manual", "spend"):
            self.store.set_action(action_id, "awaiting_approval", note + "\nWaiting: needs a human.")
            return "awaiting_approval"
        verdict = policy.evaluate(action, self.settings, self.store.spend_this_month_usd(),
                                  self._integration_for(action) is not None)
        if not verdict.allowed:
            self.store.set_action(action_id, "awaiting_approval", f"{note}\nWaiting: {verdict.reason}")
            return "awaiting_approval"
        return self._perform_and_record(action_id, action, note)

    def approve(self, action_id: int) -> str:
        row = self.store.action(action_id)
        if row is None or row["status"] != "awaiting_approval":
            raise ValueError(f"action {action_id} is not awaiting approval")
        action = self._to_action(row)
        if action.kind in ("manual", "spend") or self._integration_for(action) is None:
            self.store.set_action(action_id, "done", (row["result"] or "") + "\nOwner approved / completed by hand.")
            return "done"
        return self._perform_and_record(action_id, action, row["result"] or "")

    def reject(self, action_id: int, reason: str = "") -> None:
        row = self.store.action(action_id)
        self.store.set_action(action_id, "rejected", ((row["result"] if row else "") or "") + f"\nRejected by owner. {reason}".rstrip())

    # ---------------------------------------------------------------- helpers
    def _to_action(self, row) -> Action:
        return Action(kind=row["kind"], title=row["title"], risk=row["risk"], department=row["department"],
                      payload=json.loads(row["payload"]), estimated_cost_usd=row["cost_usd"] or 0.0)

    def _save_payload(self, action_id: int, payload: dict) -> None:
        self.store.update_payload(action_id, {k: str(v) for k, v in payload.items()})

    def _repo_dir(self) -> Path | None:
        p = self.store.get("repo_path")
        return Path(p) if p and Path(p).exists() else None

    def _integration_for(self, action: Action) -> str | None:
        s = self.settings
        if action.kind == "publish_post":
            channel = action.payload.get("channel", "").lower()
            if channel in ("devto", "dev.to") and s.has("devto_api_key"):
                return "devto"
            if channel == "reddit" and s.has("reddit_client_id", "reddit_client_secret", "reddit_username", "reddit_password"):
                return "reddit"
            if channel in ("webhook", "x", "twitter", "linkedin", "mastodon", "bluesky") and s.has("webhook_url"):
                return "webhook"
            return None
        if action.kind == "submit_listing":
            if "github" in action.payload.get("platform", "").lower() and self._repo_dir():
                return "github"
            return None
        if action.kind in ("github_issue", "implement_feature", "write_asset"):
            return "github" if self._repo_dir() else "local"
        return None

    # ---------------------------------------------------------------- prepare
    def prepare(self, action: Action, action_id: int) -> str:
        p = dict(action.payload)
        brief = p.get("brief") or action.title
        if action.kind == "write_asset":
            asset, path = marketing.write_asset(self.llm, self.ctx, self.store, p.get("asset", "launch_post"), brief, p)
            p["prepared_path"] = path
            self._save_payload(action_id, p)
            return f"asset written: {path}"
        if action.kind == "publish_post":
            asset_type = p.get("asset") or {"devto": "launch_post", "reddit": "reddit_post", "hackernews": "show_hn",
                                             "webhook": "twitter_thread"}.get(p.get("channel", ""), "launch_post")
            asset, path = marketing.write_asset(self.llm, self.ctx, self.store, asset_type, brief, p)
            p.update(prepared_path=path, prepared_title=asset.title, prepared_body=asset.body_markdown)
            self._save_payload(action_id, p)
            return f"post drafted: {path}"
        if action.kind in ("github_issue", "implement_feature"):
            spec = engineering.write_spec(self.llm, self.ctx, brief)
            path = self.store.write_output(f"engineering/{_slug(spec.title)}.md", f"# {spec.title}\n\n{engineering.spec_markdown(spec)}\n")
            p.update(prepared_path=str(path), spec=spec.model_dump_json())
            self._save_payload(action_id, p)
            return f"spec written: {path}"
        if action.kind == "submit_listing":
            packet, path = distribution.listing_packet(self.llm, self.ctx, self.store, p.get("platform", "unknown"), p.get("notes", ""))
            p.update(prepared_path=str(path), tags=",".join(packet.tags))
            self._save_payload(action_id, p)
            return f"listing packet: {path}"
        if action.kind in ("spend", "manual"):
            lines = [f"# {action.title}", "", f"Estimated cost: {action.estimated_cost_usd:.2f} USD", ""]
            lines += [f"- **{k}**: {v}" for k, v in p.items()]
            path = self.store.write_output(f"approvals/{action_id}-{_slug(action.title)}.md", "\n".join(lines) + "\n")
            p["prepared_path"] = str(path)
            self._save_payload(action_id, p)
            return f"packet: {path}"
        return "nothing to prepare"

    # ---------------------------------------------------------------- perform
    def _perform_and_record(self, action_id: int, action: Action, note: str) -> str:
        try:
            result = self.perform(action)
        except Exception as exc:  # noqa: BLE001
            self.store.set_action(action_id, "failed", f"{note}\nperform failed: {exc}")
            return f"failed: {exc}"
        self.store.set_action(action_id, "done", f"{note}\n{result}")
        return "done"

    def perform(self, action: Action) -> str:
        p = action.payload
        repo = self._repo_dir()
        s = self.settings
        if action.kind == "write_asset":
            return "done (internal asset)"
        if action.kind == "github_issue":
            if repo is None or not gh.has_github_remote(repo):
                return "no GitHub remote; spec kept in outputs/"
            spec = FeatureSpec.model_validate_json(p["spec"])
            return "issue: " + engineering.file_issue(repo, spec)
        if action.kind == "implement_feature":
            if repo is None or not gh.has_github_remote(repo):
                return "no GitHub remote; spec kept in outputs/"
            spec = FeatureSpec.model_validate_json(p["spec"])
            issue = engineering.file_issue(repo, spec)
            if not engineering.coder_available(s):
                return f"issue filed (no coder configured): {issue}"
            return f"issue: {issue}\npull request: {engineering.implement(s, repo, spec, issue)}"
        if action.kind == "publish_post":
            channel = self._integration_for(action)
            title, body = p.get("prepared_title", action.title), p.get("prepared_body", "")
            tags = [t.strip() for t in p.get("tags", "").split(",") if t.strip()]
            if channel == "devto":
                return devto.publish_article(s.integrations["devto_api_key"], title, body, tags, canonical_url=p.get("url") or None)
            if channel == "reddit":
                return reddit.submit_post(s.integrations, p.get("subreddit", "").removeprefix("r/"), title, text=body, url=p.get("url") or None)
            if channel == "webhook":
                return webhook.send(s.integrations["webhook_url"], "publish_post",
                                    {"channel": p.get("channel"), "title": title, "body": body, "tags": tags, "url": p.get("url", "")})
            return "no integration; packet prepared for manual posting"
        if action.kind == "submit_listing":
            if self._integration_for(action) == "github" and repo is not None:
                topics = [t for t in p.get("tags", "").split(",") if t.strip()][:20]
                cmd = ["gh", "repo", "edit"] + sum([["--add-topic", t.strip().lower().replace(" ", "-")[:50]] for t in topics], [])
                if topics:
                    from .ingest.common import run
                    run(cmd, cwd=repo, timeout=60)
                return f"GitHub topics set: {', '.join(topics) or 'none'}"
            return "no integration; packet prepared for manual submission"
        return "nothing to perform"


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:50] or "item"
