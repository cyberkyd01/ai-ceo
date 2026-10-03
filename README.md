# AI CEO

Point it at a GitHub repository, a VPS, or a local folder. It becomes the operator of that product:
it researches the market and competitors, sets a strategy with a real unique selling proposition,
plans each cycle, produces marketing, files feature specs and pull requests that close competitor
gaps, prepares listings for the platforms that matter, tracks money, and reflects on what worked.

It runs on Claude (`claude-opus-5` by default) through the official Anthropic SDK, with Anthropic's
server-side web search for research and Claude Code in headless mode as its engineer.

> **Deploying to a server?** Follow the step-by-step VPS guide: **[DEPLOY.md](DEPLOY.md)**

## What it does each cycle

```
observe   refresh metrics (GitHub stars/traffic, Stripe revenue, anything you record by hand)
research  competitor and market analysis with live web search   (re-runs every 14 days)
strategy  USP, positioning, pricing, OKRs, explicit non-goals   (re-runs when research or reflection says so)
finance   unit economics, budget allocation, kill criteria
decide    up to 5 scored decisions -> concrete actions (impact, confidence, reversibility, options considered)
act       run each action through the policy gate
reflect   learnings -> memory/learnings.md, rewritten company brief, strategy re-check
report    outputs/reports/cycle-NNNN.md
```

Actions the CEO can take:

| Kind | What happens | Needs |
|---|---|---|
| `write_asset` | Launch post, Show HN, Reddit post, X thread, LinkedIn post, landing copy, SEO plan, outreach email, newsletter, comparison page | nothing |
| `github_issue` | Full feature spec filed as an issue on the product repo | repo on GitHub |
| `implement_feature` | Spec -> Claude Code implements it on a branch -> draft pull request | `claude` CLI installed |
| `publish_post` | Posts to dev.to or Reddit via API, or to X/LinkedIn/etc. through your Zapier/Make/n8n webhook | credentials in `.env` |
| `submit_listing` | Complete copy-paste listing packet (Product Hunt, Hacker News, G2, AlternativeTo, ...). GitHub topics are set automatically | you submit it |
| `spend` | Written proposal with amount and kill criteria | your approval |
| `manual` | Step-by-step checklist for things only a human can do | you |

## What it will not do on its own

Creating accounts on launch platforms, entering card details, passing captchas, and anything legal
need a human. Most platforms forbid automation there. The CEO prepares everything so each of those
takes you a few minutes, and puts it in the approval queue. Money is never spent without a budget
check, and in the default `supervised` mode nothing is published without your approval.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env        # add ANTHROPIC_API_KEY, optionally dev.to / Reddit / webhook / Stripe keys
gh auth login               # GitHub CLI, used for repo stats, issues and pull requests
```

Claude Code (`claude`) on the PATH enables the engineering department to implement features.
Without it, specs are still written and filed as issues.

## Use

```bash
ai-ceo init https://github.com/you/product        # or: ai-ceo init deploy@1.2.3.4   or: ai-ceo init ./product
ai-ceo run                                        # one cycle
ai-ceo run --every 12h                            # keep running
ai-ceo status
ai-ceo approvals                                  # what is waiting for you, with the prepared packet paths
ai-ceo approve 7 8                                # performs the action (or marks it done if it was manual)
ai-ceo reject 9 --reason "not now"
ai-ceo report                                     # latest cycle report
ai-ceo metric signups 42                          # feed it numbers it cannot fetch itself
```

`--dry-run` on any command uses a fake model, so you can see the plumbing without spending anything.

For unattended operation use cron or launchd, for example `0 */12 * * * cd /path && .venv/bin/ai-ceo run`.
On a Linux server, [DEPLOY.md](DEPLOY.md) sets this up with systemd timers under a dedicated, sandboxed user.

## Autonomy policy

Set in `.env`:

- `AI_CEO_AUTONOMY=supervised` (default): publishing and spending wait in the queue. Internal work
  (assets, specs, issues, branches, draft PRs) proceeds.
- `AI_CEO_AUTONOMY=autonomous`: publishes automatically wherever an integration exists. Spend up to
  `AI_CEO_AUTO_SPEND_LIMIT_USD` per action without asking, always inside `AI_CEO_MONTHLY_BUDGET_USD`.
- `AI_CEO_MAX_LLM_USD_PER_CYCLE` hard-stops a cycle if the model spend exceeds it.

The full rules are in `ai_ceo/policy.py`.

## Where things live

```
companies/<slug>/
  state.db       decisions, actions, approvals, metrics, cycles, LLM usage
  repo/          clone of the product (GitHub sources)
  memory/        brief.md (standing summary), learnings.md (accumulated lessons)
  outputs/       dossier.json, analysis.json, strategy.json, marketing/, engineering/,
                 distribution/, approvals/, reports/
```

## Code map

- `ai_ceo/ceo.py` the loop and the CEO prompts
- `ai_ceo/executor.py` prepare/perform split and the approval re-entry
- `ai_ceo/policy.py` what may run without you
- `ai_ceo/departments/` research, strategy, marketing, distribution, engineering, finance
- `ai_ceo/integrations/` GitHub (gh CLI), dev.to, Reddit, webhook, Stripe
- `ai_ceo/platforms.py` the platform catalog and which ones have an API
- `ai_ceo/llm.py` the Anthropic SDK wrapper: adaptive thinking, structured JSON output, web tools,
  server-side refusal fallbacks, usage metering
- `ai_ceo/ingest/` GitHub clone + stats, VPS probe over SSH, local folder

Tests: `pytest` (no network or API key needed).

## Model settings

Defaults to `claude-opus-5` with adaptive thinking at `high` effort and Anthropic's server-side
refusal fallbacks enabled (`fallbacks: "default"`), so a safety decline is re-run on a fallback model
inside the same call. Change with `AI_CEO_MODEL` and `AI_CEO_EFFORT`.
