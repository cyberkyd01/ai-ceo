# Deploy AI CEO on a VPS (over SSH)

This guide takes you from a fresh SSH session to AI CEO running unattended on your server. Each company's operating cycle runs on a schedule as a systemd timer, under its own locked-down system user, and you handle approvals with one command: `sudo /opt/ai-ceo/bin/ai-ceo approvals`.

**AI CEO is a command-line agent, not a website.** It has no web interface and opens no network port, so there is no nginx, no domain and no HTTPS in this guide (step 11 explains why). Everything it does is outbound: calls to the Anthropic API, GitHub, and the optional publishing integrations.

> Tested on **Ubuntu 22.04 / 24.04 LTS** and **Debian 12**, x86_64 or arm64. Log in as root or as a sudo user. Every command uses `sudo`, which also works for root. On a minimal Debian where you are root and `sudo` is missing, first run `apt-get install -y sudo`.

## At a glance

| | |
|---|---|
| Install dir | `/opt/ai-ceo` (code, runtimes, company data), config in `/etc/ai-ceo/` |
| System user | `ai-ceo`: no login shell, no sudo, home at `/opt/ai-ceo/home` |
| Command you run | `sudo /opt/ai-ceo/bin/ai-ceo <command>` (runs the CLI as `ai-ceo` inside the same sandbox as the timers) |
| Scheduled work | `ai-ceo-cycle@<company>.timer` → `ai-ceo-cycle@<company>.service` (one operating cycle; every 12 h by default) |
| Ports | **none**. The ports reserved for this project (3114/3214/3314, Redis 6314, public 8114) are left unused |
| Runtimes | system Python 3 (3.10+) in a fresh virtualenv per release · Node.js **22** + Claude Code + GitHub CLI in `/opt/ai-ceo/runtime` (private copies) |
| Data | one SQLite `state.db` per company plus its repo clone, memory and outputs, in `/opt/ai-ceo/data/companies/<slug>/` |
| Never touched | system Python/Node, other users' files, web servers, databases, firewall, SSH server config |

## What it does on this server, and how it is contained

Read this before you install. AI CEO is an autonomous agent, and some of its actions run code on the machine:

| What it does | Host effect |
|---|---|
| Research, strategy, marketing copy | outbound HTTPS to the Anthropic API (web search runs on Anthropic's side) |
| `init <github-url>` and every cycle | `git clone` / `fetch` of your product into its data folder, plus `gh api` calls for stars and traffic |
| `github_issue`, `implement_feature` | `gh issue create`, then **Claude Code** (`claude -p`) edits the product repo and may run `npm`, `pnpm`, `yarn`, `python`, `pytest`, `make`, `go` or `cargo` there (its allowed tools). After that AI CEO commits, runs `git push` and opens a **draft PR**. The model usually rates these as *internal*, and internal actions run without asking, even in the default `supervised` mode |
| `publish_post` | dev.to / Reddit / webhook HTTP calls. In `supervised` mode they only happen after `ai-ceo approve` |
| `submit_listing` | `gh repo edit --add-topic` on your product repo |
| `init user@host` (VPS source) | `ssh -o BatchMode=yes user@host` with read-only probes (services, nginx `server_name`s, listening ports, folder listings, READMEs) |

It never needs root. This guide confines it like this:

- **Its own user.** `ai-ceo` is not in `sudo`, `docker`, `lxd` or `adm`. Don't add it: membership in `docker` or `lxd` is equivalent to root.
- **It cannot change its own code or the deploy script.** `/opt/ai-ceo`, `/opt/ai-ceo/bin` and `/etc/ai-ceo` belong to root. Every agent process runs in a systemd sandbox: `ProtectSystem=strict` (the whole filesystem read-only except `/opt/ai-ceo/data` and `/opt/ai-ceo/home`), `ProtectHome` (other users' home folders are invisible), `PrivateTmp`, `NoNewPrivileges`, a memory cap, and `IPAddressDeny=localhost`. That last one means it can't reach services that other apps bind to `127.0.0.1`, such as Redis, databases or admin panels. DNS still works.
- **Its credentials are scoped.** The GitHub token you create in step 7 is fine-grained and limited to your product repo(s).

> **Warning: two things the sandbox can't fix.**
>
> 1. **Secrets reach the product's own scripts.** Claude Code needs `ANTHROPIC_API_KEY`, and git and gh need `GH_TOKEN`. Both are in the environment when the coder runs your product's `npm test` / `make` / `python …`, so a malicious dependency in the product could read them. Use a **dedicated** Anthropic key with a **spend limit**, set in the Anthropic Console, and a GitHub token limited to the product repo.
> 2. **The per-cycle budget doesn't cover Claude Code.** `AI_CEO_MAX_LLM_USD_PER_CYCLE` caps AI CEO's own Claude calls, but the Claude Code runs it launches are billed to the same key and are **not counted**. The Console spend limit is your real cap.

## Requirements

- **Server:** Ubuntu 22.04/24.04 or Debian 12, 1 vCPU, 1 GB RAM and 5 GB free disk. 2 GB RAM is better if Claude Code will build and test your product. Python 3.10+ (every supported release ships one: 3.10, 3.11 or 3.12).
- **Network:** outbound HTTPS to `api.anthropic.com`, GitHub, nodejs.org, PyPI and npm, plus the integrations you enable. Outbound SSH only if you use VPS sources. Nothing connects *in*.
- **GitHub:** access to `cyberkyd01/ai-ceo` (step 6 adds a read-only deploy key).
- **Keys you supply:**

| Key | Required | Where to get it | What it's for |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **yes** | Anthropic Console → API keys (console.anthropic.com). Create a dedicated key and set a monthly spend limit | All reasoning (`claude-opus-5` by default), web research, and the Claude Code coder |
| `GH_TOKEN` | yes, for GitHub products | github.com/settings/personal-access-tokens/new: a **fine-grained** token, *Only select repositories* = your product. Permissions: **Contents** R/W, **Issues** R/W, **Pull requests** R/W, Metadata R. Optional: **Administration** R/W for traffic stats and setting topics | repo stats, issues, pushing `ai-ceo/*` branches, draft PRs, cloning a private product |
| `DEVTO_API_KEY` | no | dev.to → Settings → Extensions → DEV Community API Keys | `publish_post` to dev.to |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` | no | reddit.com/prefs/apps → create a **script** app, plus the posting account's login | `publish_post` to Reddit |
| `OUTBOUND_WEBHOOK_URL` | no | a Zapier / Make / n8n catch hook | fan-out to X, LinkedIn, email, … |
| `STRIPE_API_KEY` | no | Stripe → Developers → API keys → **restricted key** with read access to balance transactions | revenue metrics |

Without an optional key, those actions become step-by-step packets in the approval queue.

---

## 1. Connect and set your variables

```bash
ssh root@YOUR_SERVER_IP        # or: ssh youruser@YOUR_SERVER_IP
```

This block is the only place you configure the deployment. It writes `/etc/ai-ceo/deploy.conf`, and every later block reads that file. To change a value later, edit it here and paste the block again, then re-run step 9. If you changed `INSTALL_CLAUDE_CODE`, also re-run steps 5 and 7.

```bash
(
set -euo pipefail
# ---------- edit these ----------
BRANCH="main"
CYCLE_SCHEDULE="*-*-* 00/12:00:00"   # systemd calendar: every 12 h (00:00 and 12:00). Daily at 06:00 = "*-*-* 06:00:00"
INSTALL_CLAUDE_CODE="yes"            # "yes" = the engineering department implements features as draft PRs; "no" = issues only
AGENT_MEMORY_MAX="2G"                # memory cap for every agent process (incl. Claude Code and product builds); "infinity" = no cap
BLOCK_LOCALHOST="yes"                # "yes" = the agent cannot connect to 127.0.0.1 services; "no" if your product's tests need a local server
RUN_TESTS="yes"                      # run AI CEO's offline test suite before each deploy switches over
# ---------- usually leave as is ----------
APP="ai-ceo"
NODE_MAJOR="22"

sudo mkdir -p "/etc/$APP"
sudo tee "/etc/$APP/deploy.conf" >/dev/null <<EOF
APP="$APP"
APP_USER="$APP"
APP_HOME="/opt/$APP"
REPO_URL="git@github.com:cyberkyd01/ai-ceo.git"
BRANCH="$BRANCH"
CYCLE_SCHEDULE="$CYCLE_SCHEDULE"
INSTALL_CLAUDE_CODE="$INSTALL_CLAUDE_CODE"
AGENT_MEMORY_MAX="$AGENT_MEMORY_MAX"
BLOCK_LOCALHOST="$BLOCK_LOCALHOST"
RUN_TESTS="$RUN_TESTS"
NODE_MAJOR="$NODE_MAJOR"
EOF
sudo chmod 644 "/etc/$APP/deploy.conf"
cat "/etc/$APP/deploy.conf"
)
```

You should see your values printed back.

## 2. Preflight checks

This block only reads and changes nothing. It prints `OK`, `WARN` or `STOP` lines.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
FAIL=0
ok()   { echo "OK    $*"; }
warn() { echo "WARN  $*"; }
stop() { echo "STOP  $*"; FAIL=1; }

. /etc/os-release
case "$ID:$VERSION_ID" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ok "OS: $PRETTY_NAME" ;;
  *) warn "OS: $PRETTY_NAME is not one of the tested systems (Ubuntu 22.04/24.04, Debian 12)" ;;
esac
case "$(uname -m)" in x86_64|aarch64) ok "CPU: $(uname -m)" ;; *) stop "CPU $(uname -m) is not supported" ;; esac
MEM=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
if [ "$MEM" -ge 1800 ]; then ok "RAM: ${MEM} MB"; elif [ "$MEM" -ge 900 ]; then warn "RAM: ${MEM} MB - fine for AI CEO, tight if Claude Code builds your product"; else stop "RAM: ${MEM} MB"; fi
DISK=$(df -Pm /opt | awk 'NR==2{print $4}')
if [ "$DISK" -ge 5000 ]; then ok "Disk: ${DISK} MB free in /opt"; else warn "Disk: only ${DISK} MB free in /opt (5 GB recommended)"; fi

if command -v python3 >/dev/null && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then ok "Python: $(python3 -V) (3.10+ needed)"
elif command -v python3 >/dev/null; then stop "Python: $(python3 -V) is older than 3.10"
else ok "Python: not installed yet - step 3 installs python3"; fi

SDV=$(systemctl --version | awk 'NR==1{print $2}')
if [ "$SDV" -ge 240 ]; then ok "systemd $SDV"; else stop "systemd $SDV is too old (240+ needed for the sandbox)"; fi
if systemd-analyze calendar "$CYCLE_SCHEDULE" >/dev/null 2>&1; then ok "Schedule '$CYCLE_SCHEDULE' - next: $(systemd-analyze calendar "$CYCLE_SCHEDULE" | awk -F': ' '/Next elapse/{print $2}')"
else stop "CYCLE_SCHEDULE '$CYCLE_SCHEDULE' is not a valid systemd calendar expression"; fi
if [ "$(stat -fc %T /sys/fs/cgroup)" = cgroup2fs ]; then ok "cgroup v2 (localhost blocking and memory cap are enforced)"
else warn "cgroup v1 / container VPS: IPAddressDeny and MemoryMax may be ignored - the rest of the sandbox still applies"; fi
NS="$(awk '/^nameserver/{print $2}' /etc/resolv.conf | tr '\n' ' ')"
ok "DNS servers: $NS(any 127.x resolver is allowed through the localhost block automatically)"

for u in https://api.anthropic.com https://github.com https://nodejs.org; do
  if curl -sS -o /dev/null --max-time 10 "$u"; then ok "Outbound HTTPS: $u"; else stop "Cannot reach $u"; fi
done
if id -nG ai-ceo 2>/dev/null | grep -qwE 'sudo|docker|lxd|adm|wheel'; then stop "user ai-ceo already exists and is in a privileged group: $(id -nG ai-ceo)"; fi

echo
if [ "$FAIL" = 0 ]; then echo "Preflight passed."; else echo "Fix the STOP lines above, then re-run this block."; fi
EOF
```

You should see `Preflight passed.`

## 3. Install system packages

This step only adds packages and never upgrades or removes anything.

```bash
sudo bash -euo pipefail <<'EOF'
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1   # additive only: needrestart must not restart other services
source /etc/ai-ceo/deploy.conf
cd /tmp
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
MISSING_PKGS=""; for p in git curl ca-certificates python3 python3-venv openssh-client xz-utils sudo; do dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'ok installed' || MISSING_PKGS="$MISSING_PKGS $p"; done
if [ -n "$MISSING_PKGS" ]; then apt-get install -y --no-install-recommends $MISSING_PKGS; fi   # only what's missing - never upgrades installed packages
echo "OK: $(git --version), $(python3 -V)"
EOF
```

## 4. Create the app user and folders

`/opt/ai-ceo`, `/opt/ai-ceo/bin` and `/etc/ai-ceo` belong to **root**. The agent can't touch the deploy script that you run with sudo, or its own sandbox settings. It owns only its home, its data and the private runtimes. The home folder is `/opt/ai-ceo/home` rather than `/opt/ai-ceo` because git, gh and Claude Code write their own config files there.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --user-group --home-dir "$APP_HOME/home" --shell /usr/sbin/nologin "$APP_USER"
[ "$(getent passwd "$APP_USER" | cut -d: -f6)" = "$APP_HOME/home" ] || usermod --home "$APP_HOME/home" "$APP_USER"
install -d -m 755 -o root -g "$APP_USER" "$APP_HOME"
install -d -m 755 -o root -g root "$APP_HOME/bin"
install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$APP_HOME/home" "$APP_HOME/home/.ssh"
for d in .cache .config .local .npm; do install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$APP_HOME/home/$d"; done
for d in releases repo shared runtime runtime/bin data data/companies; do install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$APP_HOME/$d"; done
id "$APP_USER"
ls -la "$APP_HOME"
EOF
```

You should see `groups=…(ai-ceo)` and nothing else, `bin` owned by `root`, and the other folders owned by `ai-ceo`.

## 5. Install the runtimes (isolated)

- **Python.** The system `python3` (3.10, 3.11 or 3.12) is new enough. Each release gets its own virtualenv in step 10, so nothing is installed into the system Python.
- **GitHub CLI (`gh`).** The official release tarball, checksum-verified, goes into `/opt/ai-ceo/runtime/gh`. No apt repository is added.
- **Node.js 22 + Claude Code + pnpm** (only if `INSTALL_CLAUDE_CODE="yes"`). The official Node tarball goes into `/opt/ai-ceo/runtime/node`, and `@anthropic-ai/claude-code` and `pnpm` are installed into that runtime only. Claude Code needs Node 22 or newer, and the coder uses this `node`/`npm`/`pnpm` to build and test JavaScript products.
- `runtime/bin/python` is a private symlink to `python3`, because the coder's allowed tools call `python`. It is not a system-wide `python` command.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
as_app() { sudo -u "$APP_USER" -H env HOME="$APP_HOME/home" PATH="$APP_HOME/runtime/node/bin:$APP_HOME/runtime/bin:/usr/bin:/bin" "$@"; }
case "$(uname -m)" in x86_64) NARCH=x64; GARCH=amd64 ;; aarch64|arm64) NARCH=arm64; GARCH=arm64 ;; *) echo "Unsupported CPU: $(uname -m)"; exit 1 ;; esac

# --- GitHub CLI ---
GHV="$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest | grep -oE '"tag_name": *"v[0-9.]+"' | grep -oE '[0-9][0-9.]*' | head -1)"
GHF="gh_${GHV}_linux_${GARCH}.tar.gz"
TMP="$(mktemp -d)"
curl -fsSL "https://github.com/cli/cli/releases/download/v${GHV}/${GHF}" -o "$TMP/$GHF"
(cd "$TMP" && curl -fsSL "https://github.com/cli/cli/releases/download/v${GHV}/gh_${GHV}_checksums.txt" | grep " ${GHF}\$" | sha256sum -c -)
rm -rf "$APP_HOME/runtime/gh" && mkdir -p "$APP_HOME/runtime/gh"
tar -xzf "$TMP/$GHF" -C "$APP_HOME/runtime/gh" --strip-components=1
ln -sfn ../gh/bin/gh "$APP_HOME/runtime/bin/gh"
ln -sfn /usr/bin/python3 "$APP_HOME/runtime/bin/python"
rm -rf "$TMP"

# --- Node.js + Claude Code + pnpm ---
if [ "$INSTALL_CLAUDE_CODE" = yes ]; then
  BASE="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"
  TARBALL="$(curl -fsSL "$BASE/SHASUMS256.txt" | grep -oE "node-v[0-9.]+-linux-${NARCH}\.tar\.xz" | head -1)"
  TMP="$(mktemp -d)"
  curl -fsSL "$BASE/$TARBALL" -o "$TMP/$TARBALL"
  (cd "$TMP" && curl -fsSL "$BASE/SHASUMS256.txt" | grep " $TARBALL\$" | sha256sum -c -)
  rm -rf "$APP_HOME/runtime/node" && mkdir -p "$APP_HOME/runtime/node"
  tar -xJf "$TMP/$TARBALL" -C "$APP_HOME/runtime/node" --strip-components=1
  rm -rf "$TMP"
fi
chown -R "$APP_USER:$APP_USER" "$APP_HOME/runtime"
if [ "$INSTALL_CLAUDE_CODE" = yes ]; then
  as_app "$APP_HOME/runtime/node/bin/npm" install -g --no-audit --no-fund @anthropic-ai/claude-code@latest pnpm@10 </dev/null
  echo "node $("$APP_HOME/runtime/node/bin/node" -v), $(as_app env DISABLE_AUTOUPDATER=1 "$APP_HOME/runtime/node/bin/claude" --version </dev/null)"
fi
as_app "$APP_HOME/runtime/bin/gh" --version | sed -n 1p
EOF
```

You should see `gh version 2.x.x`. With Claude Code you should also see `node v22.x.x, 2.x.x (Claude Code)`.

## 6. Give the server read access to the repo

This deploy key is used **only** by `deploy.sh` to fetch AI CEO's own code. It doesn't give the agent access to your product repos; the agent uses the token from step 7 for those.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
K="$APP_HOME/home/.ssh/deploy_key"
[ -f "$K" ] || sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N "" -C "$APP-deploy@$(hostname)" -f "$K" </dev/null
touch "$APP_HOME/home/.ssh/known_hosts"
grep -q '^github.com ' "$APP_HOME/home/.ssh/known_hosts" || ssh-keyscan -t ed25519 github.com 2>/dev/null >> "$APP_HOME/home/.ssh/known_hosts"
chown -R "$APP_USER:$APP_USER" "$APP_HOME/home/.ssh" && chmod 600 "$APP_HOME/home/.ssh/known_hosts"
echo; echo "Add this key at https://github.com/cyberkyd01/ai-ceo/settings/keys/new (leave 'Allow write access' UNticked):"; echo
cat "$K.pub"
EOF
```

Open **https://github.com/cyberkyd01/ai-ceo/settings/keys/new**, give it a title such as `vps-ai-ceo`, paste the printed `ssh-ed25519 …` line, leave **Allow write access** unticked, and click **Add key**. Then test it:

```bash
sudo -u ai-ceo -H ssh -i /opt/ai-ceo/home/.ssh/deploy_key -o IdentitiesOnly=yes -T git@github.com </dev/null
```

You should see `Hi cyberkyd01/ai-ceo! You've successfully authenticated, but GitHub does not provide shell access.` (That command exits with code 1, which is normal.)

> Public repo instead? Set `REPO_URL="https://github.com/cyberkyd01/ai-ceo.git"` in `/etc/ai-ceo/deploy.conf` and skip this step.

## 7. Configure the app (`.env`)

AI CEO reads `.env` from its working directory. `/opt/ai-ceo/shared/.env` is linked into each release, and the agent can read it but not change it. This block creates the file once with every setting the app reads (`ai_ceo/config.py`), asks for the two required keys with hidden input (they never land in your shell history), and points git at the private `gh` for HTTPS authentication. Re-running it keeps what you already entered.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
ENV_FILE="$APP_HOME/shared/.env"
setenv() { local t; t="$(mktemp)"; grep -v "^$1=" "$ENV_FILE" > "$t" || true; printf '%s=%s\n' "$1" "$2" >> "$t"; cat "$t" > "$ENV_FILE"; rm -f "$t"; }
getenv() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

if [ ! -f "$ENV_FILE" ]; then
  install -m 600 -o "$APP_USER" -g "$APP_USER" /dev/null "$ENV_FILE"
  cat >> "$ENV_FILE" <<'ENV'
# AI CEO settings (DEPLOY.md step 7). One KEY=value per line.
# Never put '#' inside a value: the app's .env reader treats everything after '#' as a comment.
# ---- required ----
ANTHROPIC_API_KEY=
GH_TOKEN=
# ---- model / cost ----
AI_CEO_MODEL=claude-opus-5
# low | medium | high | xhigh | max
AI_CEO_EFFORT=high
# hard stop for AI CEO's own Claude spend inside one cycle (USD). Claude Code runs are NOT counted.
AI_CEO_MAX_LLM_USD_PER_CYCLE=5
# ---- autonomy ----
# supervised = publishing and spending wait for `ai-ceo approve`. autonomous = publishes wherever an integration exists.
AI_CEO_AUTONOMY=supervised
AI_CEO_MONTHLY_BUDGET_USD=200
# per-action spend allowed without approval (autonomous mode only)
AI_CEO_AUTO_SPEND_LIMIT_USD=0
# ---- engineering ----
AI_CEO_CODER_MAX_TURNS=80
# ---- optional integrations (blank = those actions become manual packets in the approval queue) ----
DEVTO_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=
OUTBOUND_WEBHOOK_URL=
STRIPE_API_KEY=
ENV
fi
setenv AI_CEO_HOME "$APP_HOME/data/companies"
if [ "$INSTALL_CLAUDE_CODE" = yes ]; then setenv AI_CEO_CODER claude; else setenv AI_CEO_CODER none; fi

if [ -z "$(getenv ANTHROPIC_API_KEY)" ]; then
  read -rsp "Paste your Anthropic API key (sk-ant-..., input hidden): " K </dev/tty; echo
  setenv ANTHROPIC_API_KEY "$K"
fi
if [ -z "$(getenv GH_TOKEN)" ]; then
  read -rsp "Paste your fine-grained GitHub token (github_pat_..., input hidden, Enter to skip): " K </dev/tty; echo
  if [ -n "$K" ]; then setenv GH_TOKEN "$K"; fi
fi
chown "$APP_USER:$APP_USER" "$ENV_FILE" && chmod 600 "$ENV_FILE"

# git uses the private gh as its credential helper for https://github.com (token comes from GH_TOKEN)
sudo -u "$APP_USER" -H git config --global --replace-all credential.https://github.com.helper ""
sudo -u "$APP_USER" -H git config --global --add credential.https://github.com.helper "!$APP_HOME/runtime/bin/gh auth git-credential"

if printf 'x-api-key: %s\nanthropic-version: 2023-06-01\n' "$(getenv ANTHROPIC_API_KEY)" | curl -fsS -o /dev/null -H @- https://api.anthropic.com/v1/models; then
  echo "OK    Anthropic API key works"
else echo "WARN  Anthropic API key was rejected - fix it with: sudo nano $ENV_FILE"; fi
if [ -n "$(getenv GH_TOKEN)" ]; then
  sudo -u "$APP_USER" -H env GH_TOKEN="$(getenv GH_TOKEN)" "$APP_HOME/runtime/bin/gh" auth status </dev/null || echo "WARN  GitHub token was rejected"
else echo "WARN  no GH_TOKEN - GitHub products, issues and pull requests won't work"; fi
EOF
```

You should see `OK    Anthropic API key works` and `✓ Logged in to github.com account … (GH_TOKEN)`.

To add optional integrations or change the model, autonomy or budget later, run `sudo nano /opt/ai-ceo/shared/.env`. The next cycle picks up the change; nothing needs restarting. What each setting does:

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | read by the Anthropic SDK and by Claude Code |
| `GH_TOKEN` | required for GitHub | read by `gh`, and by git through the credential helper |
| `AI_CEO_MODEL`, `AI_CEO_EFFORT` | `claude-opus-5`, `high` | model and thinking effort |
| `AI_CEO_MAX_LLM_USD_PER_CYCLE` | `5` | stops a cycle once AI CEO's own Claude spend passes this |
| `AI_CEO_AUTONOMY` | `supervised` | `autonomous` publishes automatically wherever an integration exists |
| `AI_CEO_MONTHLY_BUDGET_USD`, `AI_CEO_AUTO_SPEND_LIMIT_USD` | `200`, `0` | budget for proposed spend, and how much it may spend without asking (autonomous mode only) |
| `AI_CEO_HOME` | set by this step | `/opt/ai-ceo/data/companies`. Must stay inside `/opt/ai-ceo/data` (the only writable place in the sandbox besides its home) |
| `AI_CEO_CODER`, `AI_CEO_CODER_MAX_TURNS` | `claude`, `80` | `none` = file issues only, never run Claude Code |
| `DEVTO_API_KEY`, `REDDIT_*`, `OUTBOUND_WEBHOOK_URL`, `STRIPE_API_KEY` | blank | optional integrations (see Requirements) |

## 8. Database

There is no database server to set up. Each company has its own SQLite file, `/opt/ai-ceo/data/companies/<slug>/state.db`, which holds decisions, actions, approvals, metrics, cycles and LLM usage. It is created by `ai-ceo init`. Redis isn't used either.

## 9. Sandbox, schedule and the `ai-ceo` command

This block writes:

- `ai-ceo-cycle@.service`: a template service that runs **one** operating cycle (`ai-ceo --company <slug> run`) and exits. It doesn't loop, so memory is freed between cycles, and two cycles of the same company can never overlap.
- `ai-ceo-cycle@.timer`: a template timer that starts the service on `CYCLE_SCHEDULE`, with up to 15 minutes of random delay. It catches up after a reboot (`Persistent=true`). You enable it per company in step 12.
- `/opt/ai-ceo/bin/ai-ceo`: the command you use (`init`, `approvals`, `approve`, …). It runs the CLI as `ai-ceo` through `systemd-run`, with **the same sandbox** as the timer, so approving an action that launches Claude Code is contained the same way.

Re-run this block whenever you change `CYCLE_SCHEDULE`, `AGENT_MEMORY_MAX` or `BLOCK_LOCALHOST`.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
CUR="$APP_HOME/current"
SANDBOX=(
  "NoNewPrivileges=yes" "PrivateTmp=yes" "ProtectSystem=strict" "ProtectHome=yes"
  "ReadWritePaths=$APP_HOME/data $APP_HOME/home"
  "ProtectKernelTunables=yes" "ProtectKernelModules=yes" "ProtectControlGroups=yes"
  "RestrictSUIDSGID=yes" "RestrictRealtime=yes" "LockPersonality=yes" "UMask=0077"
  "MemoryMax=$AGENT_MEMORY_MAX"
)
if [ "$BLOCK_LOCALHOST" = yes ]; then
  SANDBOX+=("IPAddressDeny=localhost")
  for ns in $( { echo 127.0.0.53; awk '/^nameserver 127\./{print $2}' /etc/resolv.conf; } | sort -u); do SANDBOX+=("IPAddressAllow=$ns"); done
fi
ENVV=(
  "HOME=$APP_HOME/home" "SHELL=/bin/bash"
  "PATH=$CUR/.venv/bin:$APP_HOME/runtime/bin:$APP_HOME/runtime/node/bin:/usr/local/bin:/usr/bin:/bin"
  "PYTHONUNBUFFERED=1" "DISABLE_AUTOUPDATER=1" "GH_NO_UPDATE_NOTIFIER=1" "GH_PROMPT_DISABLED=1"
)

{
  echo "[Unit]"
  echo "Description=AI CEO operating cycle for company %i"
  echo "After=network-online.target"
  echo "Wants=network-online.target"
  echo
  echo "[Service]"
  echo "Type=oneshot"
  echo "User=$APP_USER"
  echo "Group=$APP_USER"
  echo "WorkingDirectory=$CUR"
  for e in "${ENVV[@]}"; do echo "Environment=\"$e\""; done
  echo "ExecStart=$CUR/.venv/bin/python -m ai_ceo.cli --company %i run"
  echo "TimeoutStartSec=6h"
  echo "Nice=10"
  for p in "${SANDBOX[@]}"; do echo "$p"; done
} > "/etc/systemd/system/$APP-cycle@.service"

cat > "/etc/systemd/system/$APP-cycle@.timer" <<UNIT
[Unit]
Description=AI CEO cycle schedule for company %i

[Timer]
OnCalendar=$CYCLE_SCHEDULE
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
UNIT

{
  echo '#!/usr/bin/env bash'
  echo '# AI CEO command line, run as the ai-ceo user inside the same sandbox as the scheduled cycles.'
  echo '# Usage: sudo /opt/ai-ceo/bin/ai-ceo <init|run|status|approvals|approve|reject|report|metric|companies> ...'
  echo 'set -euo pipefail'
  echo '[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"'
  echo 'MODE=--pipe; if [ -t 0 ] && [ -t 1 ]; then MODE=--pty; fi'
  printf 'exec systemd-run --quiet --wait --collect "$MODE" --uid=%q --gid=%q \\\n' "$APP_USER" "$APP_USER"
  printf '  -p WorkingDirectory=%q \\\n' "$CUR"
  for p in "${SANDBOX[@]}"; do printf '  -p %q \\\n' "$p"; done
  for e in "${ENVV[@]}"; do printf '  -E %q \\\n' "$e"; done
  printf '  %q -m ai_ceo.cli "$@"\n' "$CUR/.venv/bin/python"
} > "$APP_HOME/bin/ai-ceo"
chown root:root "$APP_HOME/bin/ai-ceo" && chmod 755 "$APP_HOME/bin/ai-ceo"
bash -n "$APP_HOME/bin/ai-ceo"

systemctl daemon-reload
echo "Written: $APP-cycle@.service, $APP-cycle@.timer, $APP_HOME/bin/ai-ceo"
EOF
```

You should see `Written: ai-ceo-cycle@.service, ai-ceo-cycle@.timer, /opt/ai-ceo/bin/ai-ceo`. Inspect them with `systemctl cat ai-ceo-cycle@x.service` and `cat /opt/ai-ceo/bin/ai-ceo`.

## 10. Create the deploy script and deploy

`/opt/ai-ceo/bin/deploy.sh` is used for the first install **and** for every update. Each run:

1. fetches the branch into a fresh `releases/<timestamp>-<sha>` folder.
2. creates a **new virtualenv for that release** and installs the package, so a rollback restores the exact dependencies too.
3. runs AI CEO's offline test suite (fake model, no API calls) and a smoke test.
4. switches the `current` symlink, then checks that the sandboxed command works. If that check fails, it **rolls back** automatically. It keeps the last 3 releases.

There is no service to restart: the next timer run, or your next `ai-ceo` command, simply starts on the new release. A cycle that is already running finishes on the old one.

```bash
source /etc/ai-ceo/deploy.conf
sudo install -d -m 755 -o root -g root "$APP_HOME/bin"
sudo tee "$APP_HOME/bin/deploy.sh" >/dev/null <<'DEPLOY'
#!/usr/bin/env bash
# Deploys the latest commit of $BRANCH. First install and every update. Safe to re-run.
set -Eeuo pipefail
source /etc/ai-ceo/deploy.conf
[ "$(id -u)" -eq 0 ] || { echo "Run with: sudo $0"; exit 1; }
cd /

RELEASES="$APP_HOME/releases"; SHARED="$APP_HOME/shared"; REPO="$APP_HOME/repo"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"     # root uses system tools only
APP_PATH="$APP_HOME/runtime/bin:$APP_HOME/runtime/node/bin:/usr/local/bin:/usr/bin:/bin"
as_app() {
  sudo -u "$APP_USER" -H env HOME="$APP_HOME/home" PATH="$APP_PATH" \
    GIT_SSH_COMMAND="ssh -i $APP_HOME/home/.ssh/deploy_key -o IdentitiesOnly=yes" \
    bash -euo pipefail -c "$1"
}

NEW=""; SWITCHED=0
on_error() {
  if [ "$SWITCHED" = 0 ]; then
    if [ -n "$NEW" ]; then as_app "rm -rf '$NEW'" || true; fi
    echo "!! Deploy failed before switching - the current version was not touched." >&2
  else
    echo "!! Deploy failed after switching to $NEW - see 'Rolling back' in DEPLOY.md." >&2
  fi
}
trap on_error ERR

echo "==> Fetching $BRANCH"
if [ ! -d "$REPO/.git" ]; then as_app "git clone --quiet '$REPO_URL' '$REPO'"; fi
as_app "cd '$REPO' && git remote set-url origin '$REPO_URL' && git fetch --quiet --prune origin '$BRANCH' && git reset --quiet --hard 'origin/$BRANCH'"
SHA="$(as_app "cd '$REPO' && git rev-parse --short HEAD")"
NEW="$RELEASES/$(date +%Y%m%d%H%M%S)-$SHA"
as_app "mkdir -p '$NEW' && cd '$REPO' && git archive HEAD | tar -x -C '$NEW'"

echo "==> Python dependencies (fresh virtualenv, $(/usr/bin/python3 -V 2>&1))"
EXTRAS=""; if [ "$RUN_TESTS" = yes ]; then EXTRAS="[dev]"; fi
as_app "/usr/bin/python3 -m venv '$NEW/.venv' && cd '$NEW' && .venv/bin/pip install --quiet --upgrade pip && .venv/bin/pip install --quiet -e '.$EXTRAS'"

if [ "$RUN_TESTS" = yes ]; then
  echo "==> Test suite (offline, fake model)"
  as_app "cd '$NEW' && .venv/bin/python -m pytest -q -p no:cacheprovider"
fi

echo "==> Linking shared config + smoke test"
as_app "ln -sfn '$SHARED/.env' '$NEW/.env'"
as_app "cd '$NEW' && .venv/bin/python -m ai_ceo.cli --help >/dev/null && .venv/bin/python -m ai_ceo.cli companies >/dev/null"

echo "==> Switching to $NEW"
PREV="$(readlink -f "$APP_HOME/current" 2>/dev/null || true)"
ln -sfn "$NEW" "$APP_HOME/current.new" && mv -Tf "$APP_HOME/current.new" "$APP_HOME/current"
SWITCHED=1

echo "==> Checking the sandboxed command"
if "$APP_HOME/bin/ai-ceo" companies; then
  echo "==> Deployed $SHA"
  as_app "ls -1dt '$RELEASES'/*/ | tail -n +4 | xargs -r rm -rf"   # keep the last 3 releases
  exit 0
fi
trap - ERR
echo "!! Sandboxed check failed - rolling back" >&2
if [ -n "$PREV" ] && [ -d "$PREV" ]; then
  ln -sfn "$PREV" "$APP_HOME/current.new" && mv -Tf "$APP_HOME/current.new" "$APP_HOME/current"
  as_app "rm -rf '$NEW'" || true
  echo "!! Rolled back to $PREV" >&2
fi
exit 1
DEPLOY
sudo chmod 750 "$APP_HOME/bin/deploy.sh"
ls -l "$APP_HOME/bin"
```

Now run the first deploy. It takes about a minute:

```bash
sudo /opt/ai-ceo/bin/deploy.sh
```

You should see `11 passed`, then `==> Checking the sandboxed command`, then `==> Deployed <sha>`. No companies exist yet, so the check prints nothing else.

## 11. No web server, no domain

AI CEO has no HTTP interface. It never listens on a port, so there is nothing for nginx to proxy, no certificate to get, and nothing to open in a firewall. You interact with it over SSH through `sudo /opt/ai-ceo/bin/ai-ceo …`. Its reports and approval packets are Markdown files in `/opt/ai-ceo/data/companies/<slug>/outputs/`. The ports reserved for this project on the shared VPS (3114/3214/3314, 6314, 8114) stay free.

## 12. Verify, then create your first company

**a) Plumbing check without spending anything.** `--dry-run` uses a fake model. Here it uses AI CEO's own code as the "product":

```bash
sudo /opt/ai-ceo/bin/ai-ceo --dry-run init /opt/ai-ceo/current --name dry-run-test
sudo /opt/ai-ceo/bin/ai-ceo --dry-run --company dry-run-test run
sudo /opt/ai-ceo/bin/ai-ceo --company dry-run-test status
sudo rm -rf /opt/ai-ceo/data/companies/dry-run-test
```

You should see `Company created: …`, then `cycle 1: 1 decisions, 1 actions. Report: /opt/ai-ceo/data/companies/dry-run-test/outputs/reports/cycle-0001.md`, then a status summary.

**b) Your real product.** Use the **HTTPS** URL, so git authenticates with the token from step 7. This makes real Claude calls; a bootstrap usually costs well under a dollar or two.

```bash
sudo /opt/ai-ceo/bin/ai-ceo init https://github.com/YOUR-USER/YOUR-PRODUCT
sudo /opt/ai-ceo/bin/ai-ceo companies
```

The second command prints the company **slug** (by default the repo name; pass `--name "My Product"` to `init` to choose one). Run the first cycle by hand so you can watch it:

```bash
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG run
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG approvals
```

**c) Put it on the schedule:**

```bash
sudo systemctl enable --now ai-ceo-cycle@YOUR-SLUG.timer
systemctl list-timers 'ai-ceo-cycle@*' --no-pager
```

You should see the timer with its `NEXT` run time. For more products, repeat b) and c) with each slug.

## Daily use

```bash
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG status       # strategy, metrics, spend, recent cycles
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG approvals    # what is waiting for you, with packet paths
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG approve 7 8  # performs those actions
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG reject 9 --reason "not now"
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG report       # latest cycle report
sudo /opt/ai-ceo/bin/ai-ceo --company YOUR-SLUG metric signups 42
sudo ls /opt/ai-ceo/data/companies/YOUR-SLUG/outputs/approvals/   # read a packet: sudo less <path>
```

`--company` is optional while only one company exists. For a shorter command, add `alias ai-ceo='sudo /opt/ai-ceo/bin/ai-ceo'` to **your own** `~/.bashrc`.

## Optional: use a VPS as the product source (`ai-ceo init user@host`)

With a VPS source, `init` connects over SSH **once** to describe what is deployed there. Later cycles don't connect again. The probes are read-only, but their output is sent to Anthropic as context: running service names, nginx `server_name` and `proxy_pass` lines, listening ports, listings of `/opt`, `/srv` and `/var/www`, and readable READMEs. It needs **no privileges**: give it a dedicated unprivileged login, and **never** root, sudo, or the `docker` or `adm` group. Without `docker`, the `docker ps` probe just returns nothing.

First create the agent's SSH key (on this server):

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
K="$APP_HOME/home/.ssh/id_ed25519"
[ -f "$K" ] || sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N "" -C "$APP-probe@$(hostname)" -f "$K" </dev/null
cat "$K.pub"
EOF
```

**Another server.** On the target server, create a plain user (for example `sudo useradd --create-home --shell /bin/bash ai-ceo-probe`) and put the printed key into its `~/.ssh/authorized_keys`, prefixed with `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty `. Then, back on this server, trust the target's host key and run the init:

```bash
sudo -u ai-ceo -H sh -c 'ssh-keyscan -t ed25519 TARGET_HOST >> /opt/ai-ceo/home/.ssh/known_hosts'
sudo /opt/ai-ceo/bin/ai-ceo init ai-ceo-probe@TARGET_HOST
```

**This same server.** The block below creates an unprivileged `ai-ceo-probe` user whose key only works from this machine's own address. It uses the primary interface IP, not 127.0.0.1, because the sandbox blocks localhost. It doesn't change your SSH server config. If `/etc/ssh/sshd_config` has an `AllowUsers` or `AllowGroups` line, `ai-ceo-probe` must be added there by you, or this won't work.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
P="ai-ceo-probe"; PH="$APP_HOME/probe"; IP="$(hostname -I | awk '{print $1}')"
id -u "$P" >/dev/null 2>&1 || useradd --system --user-group --home-dir "$PH" --shell /bin/bash "$P"
usermod -p '*' "$P"                      # no password login possible; key login stays allowed
install -d -m 750 -o "$P" -g "$P" "$PH"
install -d -m 700 -o "$P" -g "$P" "$PH/.ssh"
echo "from=\"$IP\",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty $(cat "$APP_HOME/home/.ssh/id_ed25519.pub")" > "$PH/.ssh/authorized_keys"
chown "$P:$P" "$PH/.ssh/authorized_keys" && chmod 600 "$PH/.ssh/authorized_keys"
grep -q "^$IP " "$APP_HOME/home/.ssh/known_hosts" || ssh-keyscan -t ed25519 "$IP" 2>/dev/null >> "$APP_HOME/home/.ssh/known_hosts"
chown "$APP_USER:$APP_USER" "$APP_HOME/home/.ssh/known_hosts"
echo "Now run: sudo /opt/ai-ceo/bin/ai-ceo init $P@$IP --name my-server"
EOF
```

After the `init`, you can switch the probe off with `sudo rm /opt/ai-ceo/probe/.ssh/authorized_keys`.

---

## Updating

```bash
sudo /opt/ai-ceo/bin/deploy.sh
```

This is the same command as the first deploy. To update Claude Code or the GitHub CLI as well, re-run step 5.

## Rolling back

`deploy.sh` rolls back on its own if the new release fails its checks. To go back to the previous release by hand:

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
CUR="$(readlink -f "$APP_HOME/current")"
PREV="$(ls -1dt "$APP_HOME"/releases/*/ | sed 's:/$::' | grep -vx "$CUR" | head -1)"
[ -n "$PREV" ] || { echo "No previous release kept"; exit 1; }
ln -sfn "$PREV" "$APP_HOME/current.new" && mv -Tf "$APP_HOME/current.new" "$APP_HOME/current"
echo "Now running $PREV (the next cycle uses it)"
EOF
```

Company data in `/opt/ai-ceo/data` is shared by all releases and isn't rolled back. The app creates its SQLite tables with `CREATE TABLE IF NOT EXISTS`, so an older release can still read the data.

## Logs, status, restart

```bash
systemctl list-timers 'ai-ceo-cycle@*' --no-pager                    # schedules and next run
systemctl status 'ai-ceo-cycle@*' --no-pager                         # last result per company
sudo journalctl -u ai-ceo-cycle@YOUR-SLUG.service -n 200 --no-pager  # cycle output
sudo journalctl -u ai-ceo-cycle@YOUR-SLUG.service -f                 # follow a running cycle
sudo systemctl start --no-block ai-ceo-cycle@YOUR-SLUG.service       # run a cycle now, in the background
sudo systemctl stop ai-ceo-cycle@YOUR-SLUG.service                   # abort a running cycle
sudo systemctl disable --now ai-ceo-cycle@YOUR-SLUG.timer            # pause the schedule
readlink -f /opt/ai-ceo/current                                      # which release is live
```

A failed cycle leaves its service in the `failed` state, which `systemctl --failed` lists. The cycle is also recorded with its error in `ai-ceo status`.

## Backups and restore

Everything that matters is in **`/opt/ai-ceo/data`** (companies, SQLite databases, memory, outputs, product clones with any unpushed `ai-ceo/*` branches), **`/opt/ai-ceo/shared/.env`** (your keys) and **`/etc/ai-ceo/`**. The block below makes a consistent copy of each `state.db` while the agent may be running, then archives the rest. It skips `node_modules` folders inside product clones.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
OUT="/root/ai-ceo-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT/db" && chmod 700 "$OUT"
for db in "$APP_HOME"/data/companies/*/state.db; do
  [ -f "$db" ] || continue
  slug="$(basename "$(dirname "$db")")"
  /usr/bin/python3 -c 'import sqlite3, sys; s = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' "$db" "$OUT/db/$slug.state.db"
done
tar --exclude='*/node_modules' -czf "$OUT/ai-ceo-files.tgz" -C / "${APP_HOME#/}/data" "${APP_HOME#/}/shared" "etc/$APP"
ls -lh "$OUT" "$OUT/db"
EOF
```

Copy the folder off the server, for example with `scp -r root@SERVER:/root/ai-ceo-backup-* .`.

**Restore** on a fresh server: follow steps 1–6 and 9, extract the archive with `sudo tar -xzf ai-ceo-files.tgz -C /`, re-run step 7 (it keeps the restored keys and re-creates the git credential setting), then put the consistent database copies in place and deploy:

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
BK="$(ls -1d /root/ai-ceo-backup-* | tail -1)"        # the backup folder you copied back
for f in "$BK"/db/*.state.db; do
  [ -f "$f" ] || continue
  slug="$(basename "$f" .state.db)"
  install -m 600 -o "$APP_USER" -g "$APP_USER" "$f" "$APP_HOME/data/companies/$slug/state.db"
done
chown -R "$APP_USER:$APP_USER" "$APP_HOME/data"
echo "Restored. Now run: sudo /opt/ai-ceo/bin/deploy.sh, then re-enable each timer (step 12c)."
EOF
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `deploy.sh`: `Permission denied (publickey)` | deploy key missing or added to the wrong repo | step 6: add it to `cyberkyd01/ai-ceo` → Settings → Deploy keys, test with the `ssh -T` command there |
| `deploy.sh`: tests fail | broken commit on the branch | the running version is untouched. Fix the code, or set `RUN_TESTS="no"` in step 1 if you need to deploy anyway |
| `anthropic.AuthenticationError` / `401` in a cycle | wrong or revoked key | `sudo nano /opt/ai-ceo/shared/.env` and fix `ANTHROPIC_API_KEY` |
| `init` fails: `could not read Username for 'https://github.com'` | no `GH_TOKEN`, or the token can't see that repo | add the repo to the fine-grained token, or set `GH_TOKEN`. Re-run step 7 |
| `gh: … HTTP 403` when creating issues or PRs | token lacks Issues / Pull requests / Contents write | edit the token's permissions on GitHub |
| `issue filed (no coder configured)` | Claude Code not installed or `AI_CEO_CODER=none` | `INSTALL_CLAUDE_CODE="yes"` in step 1, then re-run steps 5, 7 and 9 |
| `coder exited 1` / Claude Code says no shell | the coder's environment | `SHELL=/bin/bash` is set by step 9. Re-run step 9 and check `journalctl -u ai-ceo-cycle@<slug>` |
| Coder can't run the product's tests: `ECONNREFUSED 127.0.0.1` | the localhost block | set `BLOCK_LOCALHOST="no"` in step 1 and re-run step 9 (the agent can then reach local services) |
| Coder or build killed, `oom-kill` in the journal | `AGENT_MEMORY_MAX` too low | raise it in step 1 (or add swap) and re-run step 9 |
| `Read-only file system` in a cycle | something writes outside `/opt/ai-ceo/data` or `/opt/ai-ceo/home` | keep `AI_CEO_HOME` under `/opt/ai-ceo/data`. Products whose tooling writes elsewhere need that path added to `ReadWritePaths` in step 9 |
| DNS errors (`Temporary failure in name resolution`) in cycles only | your resolver is on a 127.x address not in `resolv.conf` at the time of step 9 | re-run step 9 (it allows every 127.x nameserver it finds), or set `BLOCK_LOCALHOST="no"` |
| VPS `init`: `Host key verification failed` | target not in `known_hosts` | run the `ssh-keyscan` line from the VPS section |
| VPS `init`: `Permission denied (publickey)` | key not in the probe user's `authorized_keys`, wrong `from=`, or `AllowUsers` in sshd | check the probe user's `~/.ssh/authorized_keys` and `sshd_config` |
| A value in `.env` seems cut off | it contains `#` | the app's `.env` reader treats `#` as the start of a comment. Use a value without `#` (for example a different Reddit password) |
| Timer never fires | not enabled for that slug | `sudo systemctl enable --now ai-ceo-cycle@<slug>.timer`. Check with `systemctl list-timers` |
| `several companies exist; pass --company` | more than one company | add `--company <slug>` (the timers already do) |

## Uninstall

This removes only what this guide created: timers, unit files, the `ai-ceo` command, `/opt/ai-ceo` (including **all company data**, so back it up first), `/etc/ai-ceo`, and the `ai-ceo` and optional `ai-ceo-probe` users. Packages stay installed. Branches, issues and PRs the agent created on GitHub stay too.

```bash
sudo bash -euo pipefail <<'EOF'
source /etc/ai-ceo/deploy.conf
cd /tmp
for t in /etc/systemd/system/timers.target.wants/"$APP"-cycle@*.timer; do
  [ -e "$t" ] && systemctl disable --now "$(basename "$t")" || true
done
systemctl stop "$APP-cycle@*.service" 2>/dev/null || true
rm -f "/etc/systemd/system/$APP-cycle@.service" "/etc/systemd/system/$APP-cycle@.timer"
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true
id -u ai-ceo-probe >/dev/null 2>&1 && userdel ai-ceo-probe || true
rm -rf "$APP_HOME" "/etc/$APP"
id -u "$APP_USER" >/dev/null 2>&1 && userdel "$APP_USER" || true
echo "AI CEO removed."
EOF
```

Then revoke the keys: delete the deploy key at https://github.com/cyberkyd01/ai-ceo/settings/keys, revoke the fine-grained GitHub token, and delete the Anthropic API key in the Console. On any other server you used as a VPS source, remove the `ai-ceo-probe` user.

## Appendix: Caddy / Apache instead of nginx

Not applicable. AI CEO doesn't serve HTTP, so there is nothing to reverse-proxy, whichever web server owns ports 80/443 on this machine. It works the same next to nginx, Apache, Caddy or none at all.
