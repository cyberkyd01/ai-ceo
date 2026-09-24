"""The CEO loop.

One cycle = observe -> research (if stale) -> strategy (if needed) -> finance -> decide -> act -> reflect.
Each cycle is cheap by design: research only re-runs every RESEARCH_TTL_DAYS, and the LLM spend per
cycle is capped by settings.max_llm_usd_per_cycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .context import CEO_IDENTITY, Context
from .departments import finance, research, strategy
from .executor import Executor
from .ingest import ingest_github, ingest_vps, is_github_url, is_ssh_target
from .ingest.common import detect_stack, file_tree, find_readme, key_manifests, slugify
from .integrations import stripe
from .llm import LLM, BudgetExceeded
from .platforms import catalog_for, describe
from .schemas import CyclePlan, Reflection
from .state import CompanyStore

RESEARCH_TTL_DAYS = 14

DECIDE_SYSTEM = CEO_IDENTITY + """

Task: plan this operating cycle. Produce at most 5 decisions and at most 8 actions in total, ordered by
leverage. Every action must be executable by the system or completable by the owner in minutes.

Action kinds and their payload fields (all payload values are strings):
- write_asset:        asset (launch_post | show_hn | reddit_post | twitter_thread | linkedin_post | landing_copy |
                      seo_plan | outreach_email | newsletter | comparison_page), brief
- publish_post:       channel (devto | reddit | webhook | hackernews | other), asset (as above), brief,
                      subreddit (for reddit, no 'r/'), tags (comma separated), url (link to product, if a link post)
- github_issue:       brief (what to build and why; the engineering department writes the full spec)
- implement_feature:  brief (same; a coder implements it on a branch and opens a draft PR)
- submit_listing:     platform (a name from the platform catalog), notes
- spend:              what, vendor, url, amount_usd (also set estimated_cost_usd on the action)
- manual:             what, steps (one per line), url

Risk levels: read | internal (assets, specs, issues, branches, draft PRs) | publish (anything public) | spend.
Do not queue actions that duplicate ones already queued or awaiting approval. Do not plan spend the
budget cannot cover. If the product has no live URL, prioritize getting something deployable and a
landing page before any launch activity. Put the questions only the owner can answer in
`questions_for_owner`, and keep that list short."""

REFLECT_SYSTEM = CEO_IDENTITY + """

Task: end-of-cycle review. Compare what was planned with what happened, look at the metric trend, and
extract durable learnings (not restatements of the plan). Say plainly if the strategy should change.
`brief_update` replaces the standing company brief the next cycle will read first."""


class CEO:
    def __init__(self, store: CompanyStore, llm: LLM, settings: Settings):
        self.store, self.llm, self.settings = store, llm, settings

    # ---------------------------------------------------------------- bootstrap
    @classmethod
    def bootstrap(cls, source: str, settings: Settings, llm: LLM, name: str | None = None) -> "CEO":
        tmp_slug = slugify(name or Path(source.rstrip("/")).name.removesuffix(".git") or "company")
        root = settings.home / tmp_slug
        store = CompanyStore(root)
        if is_github_url(source):
            raw = ingest_github(source, store.repo_dir)
            store.put("repo_path", str(store.repo_dir))
            for k, v in raw.get("stats", {}).items():
                store.record_metric(f"github_{k}", float(v), "github")
        elif is_ssh_target(source):
            raw = ingest_vps(source)
        elif Path(source).expanduser().is_dir():
            local = Path(source).expanduser().resolve()
            raw = {"source": str(local), "readme": find_readme(local), "manifests": key_manifests(local),
                   "stack": detect_stack(local), "file_tree": file_tree(local)}
            store.put("repo_path", str(local))
        else:
            raise ValueError("source must be a GitHub URL, an ssh target (user@host), or a local directory")
        dossier = research.build_dossier(llm, raw, source)
        if name:
            dossier.name, dossier.slug = name, slugify(name)
        store.put("dossier", dossier.model_dump(mode="json"))
        store.put("source", source)
        store.write_output("dossier.json", dossier.model_dump_json(indent=2))
        if not store.read_memory("brief.md"):
            store.append_memory("brief.md", f"{dossier.name}: {dossier.one_liner}. Maturity: {dossier.maturity}. Company created {datetime.now(timezone.utc).date()}.")
        store.record_usage(None, llm.usage.log)
        return cls(store, llm, settings)

    # ---------------------------------------------------------------- one cycle
    def run_cycle(self) -> str:
        cycle_id = self.store.start_cycle()
        usage_before = len(self.llm.usage.log)
        try:
            summary = self._cycle(cycle_id)
            status = "ok"
        except BudgetExceeded as exc:
            summary, status = f"stopped: {exc}", "budget"
        except Exception as exc:  # noqa: BLE001
            summary, status = f"error: {exc}", "error"
            raise
        finally:
            new_entries = self.llm.usage.log[usage_before:]
            self.store.record_usage(cycle_id, new_entries)
            self.store.finish_cycle(cycle_id, status if 'status' in locals() else "error",
                                    summary if 'summary' in locals() else "crashed",
                                    sum(e["usd"] for e in new_entries))
        return summary

    def _cycle(self, cycle_id: int) -> str:
        self.refresh_metrics()
        ctx = Context.load(self.store, self.settings)

        # 1. research when stale
        if self.store.age_days("analysis") > RESEARCH_TTL_DAYS:
            analysis = research.analyze_market(self.llm, ctx)
            self.store.put("analysis", analysis.model_dump(mode="json"))
            self.store.write_output("analysis.json", analysis.model_dump_json(indent=2))
            ctx = Context.load(self.store, self.settings)
            self.store.put("strategy_reason", "market analysis refreshed")

        # 2. strategy when missing or flagged
        reason = self.store.get("strategy_reason")
        if ctx.strategy is None or reason:
            strat = strategy.formulate(self.llm, ctx, reason or "no strategy yet")
            self.store.put("strategy", strat.model_dump(mode="json"))
            self.store.write_output("strategy.json", strat.model_dump_json(indent=2))
            self.store.put("strategy_reason", "")
            ctx = Context.load(self.store, self.settings)

        # 3. finance view
        fin = finance.review(self.llm, ctx)
        self.store.put("finance", fin.model_dump(mode="json"))
        ctx.extra["finance"] = fin.model_dump(mode="json")

        # 4. decide
        plan = self.decide(ctx)
        results: list[str] = []
        executor = Executor(self.store, self.llm, self.settings, ctx)
        for decision in plan.decisions:
            d_id = self.store.add_decision(cycle_id, decision.title, decision.model_dump(mode="json"))
            for action in decision.actions:
                a_id = self.store.add_action(d_id, cycle_id, action.kind, action.title, action.risk, action.department,
                                             action.payload, action.estimated_cost_usd, "queued")
                outcome = executor.handle(a_id)
                results.append(f"#{a_id} {action.kind} '{action.title}' -> {outcome}")

        # 5. reflect
        reflection = self.reflect(ctx, plan, results)
        if reflection.learnings:
            stamp = datetime.now(timezone.utc).date().isoformat()
            self.store.append_memory("learnings.md", "\n".join(f"- {stamp}: {l}" for l in reflection.learnings))
        if reflection.brief_update.strip():
            (self.store.memory_dir / "brief.md").write_text(reflection.brief_update.strip() + "\n")
        if not reflection.strategy_still_valid:
            self.store.put("strategy_reason", "; ".join(reflection.suggested_strategy_changes) or "reflection flagged strategy")

        report = self.write_report(cycle_id, ctx, plan, results, reflection, fin)
        return f"cycle {cycle_id}: {len(plan.decisions)} decisions, {len(results)} actions. Report: {report}"

    # ---------------------------------------------------------------- LLM steps
    def decide(self, ctx: Context) -> CyclePlan:
        catalog = describe(catalog_for(ctx.dossier.category))
        fin = json.dumps(ctx.extra.get("finance", {}), indent=2)
        user = (f"{ctx.company_block()}\n\n{ctx.operations_block()}\n\n## Finance view\n{fin}\n\n"
                f"## Platform catalog for this category\n{catalog}\n\nPlan this cycle.")
        return self.llm.structured("ceo.decide", DECIDE_SYSTEM, user, CyclePlan, max_tokens=20000)

    def reflect(self, ctx: Context, plan: CyclePlan, results: list[str]) -> Reflection:
        history = {k: self.store.metric_history(k, 12) for k in ctx.metrics}
        user = (f"{ctx.company_block()}\n\n## This cycle's plan\n{plan.model_dump_json(indent=2)}\n\n"
                f"## Execution results\n" + "\n".join(results) + f"\n\n## Metric history\n{json.dumps(history, indent=2)}\n\nReview the cycle.")
        return self.llm.structured("ceo.reflect", REFLECT_SYSTEM, user, Reflection, effort="medium")

    # ---------------------------------------------------------------- metrics
    def refresh_metrics(self) -> None:
        source = self.store.get("source", "")
        if is_github_url(source):
            from .ingest.github import parse_repo, repo_stats
            owner, name = parse_repo(source)
            for k, v in repo_stats(owner, name).get("stats", {}).items():
                self.store.record_metric(f"github_{k}", float(v), "github")
        key = self.settings.integrations.get("stripe_api_key")
        if key:
            try:
                for k, v in stripe.revenue_last_30d(key).items():
                    self.store.record_metric(k, v, "stripe")
            except RuntimeError as exc:
                self.store.append_memory("learnings.md", f"- stripe metrics failed: {exc}")

    # ---------------------------------------------------------------- report
    def write_report(self, cycle_id: int, ctx: Context, plan: CyclePlan, results: list[str], reflection: Reflection, fin) -> str:
        awaiting = self.store.actions(status="awaiting_approval")
        md = [f"# Cycle {cycle_id} report: {ctx.dossier.name}", f"_{datetime.now(timezone.utc).isoformat(timespec='minutes')}_", "",
              "## Situation", plan.situation, "", "## Priorities", *[f"{i}. {p}" for i, p in enumerate(plan.priorities, 1)], "",
              "## Decisions"]
        for d in plan.decisions:
            md += [f"### {d.title}", d.rationale, f"- Options considered: {'; '.join(d.options_considered)}",
                   f"- Impact {d.expected_impact}/5, confidence {d.confidence}/5, {d.reversibility}", ""]
        md += ["## Actions", *[f"- {r}" for r in results], ""]
        if awaiting:
            md += ["## Waiting for you", *[f"- #{a['id']} {a['title']} ({a['kind']}): see {json.loads(a['payload']).get('prepared_path', 'queue')}" for a in awaiting], ""]
        if plan.questions_for_owner:
            md += ["## Questions for the owner", *[f"- {q}" for q in plan.questions_for_owner], ""]
        md += ["## Finance", fin.unit_economics, fin.burn_note, "Budget: " + ", ".join(f"{k} {v:.0f} USD" for k, v in fin.budget_allocation.items()), "",
               "## Reflection", "Worked: " + "; ".join(reflection.what_worked or ["n/a"]),
               "Did not: " + "; ".join(reflection.what_did_not or ["n/a"]),
               "Learnings: " + "; ".join(reflection.learnings or ["n/a"]),
               f"Strategy still valid: {reflection.strategy_still_valid}", "",
               f"LLM spend this cycle: {sum(e['usd'] for e in self.llm.usage.log):.2f} USD"]
        path = self.store.write_output(f"reports/cycle-{cycle_id:04d}.md", "\n".join(md) + "\n")
        return str(path)
