"""Command-line interface.

  ai-ceo init <github-url | user@host | ./local-dir> [--name NAME]
  ai-ceo run [--every 6h] [--max-cycles N] [--dry-run]
  ai-ceo status | approvals | approve <id> | reject <id> | report | metric <key> <value> | companies
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .ceo import CEO
from .config import Settings
from .context import Context
from .executor import Executor
from .llm import Claude, FakeLLM
from .state import CompanyStore


def _llm(settings: Settings, dry_run: bool):
    if dry_run:
        return FakeLLM()
    return Claude(model=settings.model, effort=settings.effort, budget_usd=settings.max_llm_usd_per_cycle)


def _companies(settings: Settings) -> list[Path]:
    if not settings.home.exists():
        return []
    return sorted(p for p in settings.home.iterdir() if (p / "state.db").exists())


def _store(settings: Settings, slug: str | None) -> CompanyStore:
    companies = _companies(settings)
    if slug:
        root = settings.home / slug
        if not (root / "state.db").exists():
            sys.exit(f"no company '{slug}' under {settings.home}")
        return CompanyStore(root)
    if len(companies) == 1:
        return CompanyStore(companies[0])
    if not companies:
        sys.exit("no companies yet; run `ai-ceo init <source>`")
    sys.exit("several companies exist; pass --company <slug>: " + ", ".join(p.name for p in companies))


def _interval(text: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd])", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("interval like 30m, 6h, 1d")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def cmd_init(args, settings):
    llm = _llm(settings, args.dry_run)
    ceo = CEO.bootstrap(args.source, settings, llm, name=args.name)
    d = ceo.store.get("dossier")
    print(f"Company created: {d['name']} ({ceo.store.root})")
    print(f"  {d['one_liner']}\n  category={d['category']} maturity={d['maturity']} stack={', '.join(d['stack'])}")
    print(f"  gaps: {'; '.join(d['notable_gaps']) or 'none noted'}")
    print(f"LLM spend: {llm.usage.usd:.2f} USD. Next: `ai-ceo run` (add --every 6h to keep it running).")


def cmd_run(args, settings):
    store = _store(settings, args.company)
    cycles = 0
    while True:
        llm = _llm(settings, args.dry_run)
        ceo = CEO(store, llm, settings)
        print(f"[{time.strftime('%Y-%m-%d %H:%M')}] starting cycle ...")
        try:
            print(ceo.run_cycle())
        except Exception as exc:  # noqa: BLE001 - keep the scheduler alive; the cycle is recorded as an error
            print(f"cycle failed: {exc}", file=sys.stderr)
            if not args.every:
                raise
        awaiting = store.actions(status="awaiting_approval")
        if awaiting:
            print(f"{len(awaiting)} action(s) waiting for approval: `ai-ceo approvals`")
        cycles += 1
        if not args.every or (args.max_cycles and cycles >= args.max_cycles):
            break
        print(f"sleeping {args.every}s")
        time.sleep(args.every)


def cmd_status(args, settings):
    store = _store(settings, args.company)
    d = store.get("dossier")
    print(f"{d['name']} - {d['one_liner']}\n  root: {store.root}\n  source: {store.get('source')}")
    strat = store.get("strategy")
    if strat:
        print(f"  USP: {strat['usp']}")
    print("  metrics:", json.dumps(store.latest_metrics()) or "{}")
    print(f"  spend this month: {store.spend_this_month_usd():.2f} USD of {settings.monthly_budget_usd:.0f}")
    print("  cycles:")
    for c in store.cycles(5):
        print(f"    #{c['id']} {c['started_at'][:16]} {c['status']} llm={c['llm_usd']:.2f} USD  {c['summary'] or ''}")
    counts = {}
    for a in store.actions(limit=500):
        counts[a["status"]] = counts.get(a["status"], 0) + 1
    print("  actions:", json.dumps(counts))


def cmd_approvals(args, settings):
    store = _store(settings, args.company)
    rows = store.actions(status="awaiting_approval")
    if not rows:
        print("nothing waiting")
        return
    for a in rows:
        p = json.loads(a["payload"])
        print(f"#{a['id']} [{a['kind']}/{a['risk']}] {a['title']}  cost={a['cost_usd']:.0f} USD")
        if p.get("prepared_path"):
            print(f"    packet: {p['prepared_path']}")
        last = (a["result"] or "").strip().splitlines()
        if last:
            print(f"    {last[-1]}")
    print("\napprove with `ai-ceo approve <id>`, reject with `ai-ceo reject <id>`")


def cmd_approve(args, settings):
    store = _store(settings, args.company)
    ctx = Context.load(store, settings)
    ex = Executor(store, _llm(settings, args.dry_run), settings, ctx)
    for aid in args.ids:
        print(f"#{aid}: {ex.approve(aid)}")
        row = store.action(aid)
        print("   ", (row["result"] or "").strip().splitlines()[-1])


def cmd_reject(args, settings):
    store = _store(settings, args.company)
    ctx = Context.load(store, settings)
    ex = Executor(store, FakeLLM(), settings, ctx)
    for aid in args.ids:
        ex.reject(aid, args.reason or "")
        print(f"#{aid}: rejected")


def cmd_report(args, settings):
    store = _store(settings, args.company)
    reports = sorted((store.outputs_dir / "reports").glob("cycle-*.md"))
    if not reports:
        print("no reports yet")
        return
    print(reports[-1].read_text())


def cmd_metric(args, settings):
    store = _store(settings, args.company)
    store.record_metric(args.key, float(args.value), "owner")
    print(f"recorded {args.key}={args.value}")


def cmd_companies(args, settings):
    for p in _companies(settings):
        d = CompanyStore(p).get("dossier") or {}
        print(f"{p.name:24} {d.get('one_liner', '')}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ai-ceo", description="Autonomous AI CEO for a software product.")
    ap.add_argument("--company", help="company slug (needed only when several exist)")
    ap.add_argument("--dry-run", action="store_true", help="use a fake model; exercises the plumbing without API calls")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a company from a GitHub repo, a VPS, or a local folder")
    s.add_argument("source"); s.add_argument("--name"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("run", help="run one operating cycle (or keep running with --every)")
    s.add_argument("--every", type=_interval, help="e.g. 6h, 1d"); s.add_argument("--max-cycles", type=int)
    s.set_defaults(fn=cmd_run)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("approvals").set_defaults(fn=cmd_approvals)
    s = sub.add_parser("approve"); s.add_argument("ids", type=int, nargs="+"); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("reject"); s.add_argument("ids", type=int, nargs="+"); s.add_argument("--reason"); s.set_defaults(fn=cmd_reject)
    sub.add_parser("report", help="print the latest cycle report").set_defaults(fn=cmd_report)
    s = sub.add_parser("metric", help="record a metric by hand, e.g. signups 42"); s.add_argument("key"); s.add_argument("value"); s.set_defaults(fn=cmd_metric)
    sub.add_parser("companies").set_defaults(fn=cmd_companies)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    args.fn(args, settings)


if __name__ == "__main__":
    main()
