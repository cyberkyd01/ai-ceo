from __future__ import annotations

import re
import subprocess
from pathlib import Path

MANIFESTS = {
    "package.json": "node", "pyproject.toml": "python", "requirements.txt": "python", "go.mod": "go",
    "Cargo.toml": "rust", "Gemfile": "ruby", "pom.xml": "java", "build.gradle": "java", "composer.json": "php",
    "Dockerfile": "docker", "docker-compose.yml": "docker-compose", "docker-compose.yaml": "docker-compose",
    "next.config.js": "nextjs", "next.config.mjs": "nextjs", "vite.config.ts": "vite", "tailwind.config.js": "tailwind",
    "manifest.json": "browser-extension?", "Package.swift": "swift", "pubspec.yaml": "flutter",
}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".next", "target", "vendor"}


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "company"


def file_tree(root: Path, max_entries: int = 400) -> str:
    lines: list[str] = []
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            lines.append(str(p.relative_to(root)))
        if len(lines) >= max_entries:
            lines.append(f"... (truncated at {max_entries} files)")
            break
    return "\n".join(lines)


def detect_stack(root: Path) -> list[str]:
    found: list[str] = []
    for name, label in MANIFESTS.items():
        if (root / name).exists() and label not in found:
            found.append(label)
    return found


def read_head(path: Path, limit: int = 12000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except OSError:
        return ""


def find_readme(root: Path) -> str:
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        p = root / name
        if p.exists():
            return read_head(p)
    return ""


def key_manifests(root: Path) -> str:
    parts = []
    for name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "docker-compose.yml", "Dockerfile"):
        p = root / name
        if p.exists():
            parts.append(f"--- {name} ---\n{read_head(p, 3000)}")
    return "\n".join(parts)
