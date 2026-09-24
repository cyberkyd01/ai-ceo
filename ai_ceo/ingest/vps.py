"""Inspect a VPS over SSH and gather raw facts about what is deployed there.

Target formats: `ssh://user@host[:port]` or plain `user@host`. Uses the local ssh client and whatever
keys/agent are configured. Only read-only commands are run.
"""
from __future__ import annotations

import re
import shlex

from .common import run

SSH_RE = re.compile(r"^(?:ssh://)?([\w.-]+@[\w.-]+)(?::(\d+))?/?$")

PROBES = {
    "system": "uname -a; cat /etc/os-release 2>/dev/null | head -3; uptime",
    "services": "systemctl list-units --type=service --state=running --no-pager 2>/dev/null | head -60",
    "docker": "docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>/dev/null",
    "compose_files": "ls -1 /opt/*/docker-compose.y*ml /srv/*/docker-compose.y*ml ~/*/docker-compose.y*ml 2>/dev/null",
    "nginx": "ls /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null; grep -rhE 'server_name|proxy_pass|root ' /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null | head -60",
    "caddy": "cat /etc/caddy/Caddyfile 2>/dev/null | head -80",
    "ports": "ss -tlnp 2>/dev/null | head -40",
    "apps": "ls -la /var/www /opt /srv ~ 2>/dev/null | head -80",
    "readmes": "for f in /var/www/*/README.md /opt/*/README.md /srv/*/README.md ~/*/README.md; do [ -f \"$f\" ] && echo \"=== $f\" && head -80 \"$f\"; done 2>/dev/null",
    "env_hints": "ls -a /var/www/* /opt/* /srv/* ~/* 2>/dev/null | grep -E '^\\.env|package.json|pyproject.toml|go.mod|Cargo.toml' | head -40",
    "crontab": "crontab -l 2>/dev/null | head -20",
}


def is_ssh_target(source: str) -> bool:
    return bool(SSH_RE.match(source.strip()))


def ingest_vps(source: str) -> dict:
    m = SSH_RE.match(source.strip())
    if not m:
        raise ValueError(f"not an ssh target: {source}")
    userhost, port = m.group(1), m.group(2)
    base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if port:
        base += ["-p", port]
    script = "\n".join(f"echo '##### {k}'; {v}" for k, v in PROBES.items())
    out = run(base + [userhost, f"bash -s <<'AICEO_EOF'\n{script}\nAICEO_EOF"], timeout=180)
    sections: dict[str, str] = {}
    current = "preamble"
    for line in out.splitlines():
        if line.startswith("##### "):
            current = line[6:].strip()
            sections[current] = ""
        else:
            sections[current] = sections.get(current, "") + line + "\n"
    return {"source": source, "host": userhost, "probes": sections}
