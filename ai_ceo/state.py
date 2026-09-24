"""Per-company persistent state: a SQLite database plus a plain-text memory folder.

Layout under <AI_CEO_HOME>/<slug>/:
  state.db        decisions, actions, approvals, metrics, cycles, llm usage
  repo/           clone of the product repository (if any)
  memory/         brief.md, learnings.md (read by the CEO every cycle)
  outputs/        analysis JSON/MD, marketing assets, listing packets, reports
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
  status TEXT NOT NULL, summary TEXT, llm_usd REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER, created_at TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT NOT NULL, outcome TEXT);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, decision_id INTEGER, cycle_id INTEGER, created_at TEXT NOT NULL,
  kind TEXT NOT NULL, title TEXT NOT NULL, risk TEXT NOT NULL, department TEXT NOT NULL,
  payload TEXT NOT NULL, cost_usd REAL DEFAULT 0,
  status TEXT NOT NULL,            -- queued | awaiting_approval | approved | done | failed | rejected
  result TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, key TEXT NOT NULL, value REAL NOT NULL, source TEXT);
CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, cycle_id INTEGER, label TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, usd REAL);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CompanyStore:
    def __init__(self, root: Path):
        self.root = root
        self.repo_dir = root / "repo"
        self.memory_dir = root / "memory"
        self.outputs_dir = root / "outputs"
        for d in (self.root, self.memory_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "state.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---- key/value documents (dossier, analysis, strategy ...) --------------------
    def put(self, key: str, value: Any) -> None:
        payload = value if isinstance(value, str) else json.dumps(value)
        self.db.execute("INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                        (key, payload, now()))
        self.db.commit()

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]

    def updated_at(self, key: str) -> datetime | None:
        row = self.db.execute("SELECT updated_at FROM kv WHERE key=?", (key,)).fetchone()
        return datetime.fromisoformat(row["updated_at"]) if row else None

    def age_days(self, key: str) -> float:
        ts = self.updated_at(key)
        if ts is None:
            return float("inf")
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400

    # ---- cycles -------------------------------------------------------------------
    def start_cycle(self) -> int:
        cur = self.db.execute("INSERT INTO cycles(started_at,status) VALUES(?,?)", (now(), "running"))
        self.db.commit()
        return int(cur.lastrowid)

    def finish_cycle(self, cycle_id: int, status: str, summary: str, llm_usd: float) -> None:
        self.db.execute("UPDATE cycles SET finished_at=?, status=?, summary=?, llm_usd=? WHERE id=?",
                        (now(), status, summary, llm_usd, cycle_id))
        self.db.commit()

    def cycles(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ---- decisions & actions -------------------------------------------------------
    def add_decision(self, cycle_id: int, title: str, body: dict) -> int:
        cur = self.db.execute("INSERT INTO decisions(cycle_id,created_at,title,body) VALUES(?,?,?,?)",
                              (cycle_id, now(), title, json.dumps(body)))
        self.db.commit()
        return int(cur.lastrowid)

    def add_action(self, decision_id: int | None, cycle_id: int | None, kind: str, title: str, risk: str,
                   department: str, payload: dict, cost_usd: float, status: str) -> int:
        cur = self.db.execute(
            "INSERT INTO actions(decision_id,cycle_id,created_at,kind,title,risk,department,payload,cost_usd,status,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (decision_id, cycle_id, now(), kind, title, risk, department, json.dumps(payload), cost_usd, status, now()))
        self.db.commit()
        return int(cur.lastrowid)

    def set_action(self, action_id: int, status: str, result: str | None = None) -> None:
        self.db.execute("UPDATE actions SET status=?, result=COALESCE(?, result), updated_at=? WHERE id=?",
                        (status, result, now(), action_id))
        self.db.commit()

    def update_payload(self, action_id: int, payload: dict) -> None:
        self.db.execute("UPDATE actions SET payload=?, updated_at=? WHERE id=?", (json.dumps(payload), now(), action_id))
        self.db.commit()

    def action(self, action_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()

    def actions(self, status: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if status:
            return self.db.execute("SELECT * FROM actions WHERE status=? ORDER BY id DESC LIMIT ?",
                                   (status, limit)).fetchall()
        return self.db.execute("SELECT * FROM actions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def recent_decisions(self, limit: int = 15) -> list[dict]:
        rows = self.db.execute("SELECT d.*, (SELECT group_concat(a.status) FROM actions a WHERE a.decision_id=d.id) AS statuses "
                               "FROM decisions d ORDER BY d.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ---- metrics ------------------------------------------------------------------
    def record_metric(self, key: str, value: float, source: str = "auto") -> None:
        self.db.execute("INSERT INTO metrics(at,key,value,source) VALUES(?,?,?,?)", (now(), key, value, source))
        self.db.commit()

    def latest_metrics(self) -> dict[str, float]:
        rows = self.db.execute("SELECT key, value FROM metrics m WHERE id = (SELECT MAX(id) FROM metrics WHERE key=m.key)").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def metric_history(self, key: str, limit: int = 30) -> list[tuple[str, float]]:
        rows = self.db.execute("SELECT at, value FROM metrics WHERE key=? ORDER BY id DESC LIMIT ?", (key, limit)).fetchall()
        return [(r["at"], r["value"]) for r in reversed(rows)]

    # ---- llm usage ----------------------------------------------------------------
    def record_usage(self, cycle_id: int | None, entries: list[dict]) -> None:
        self.db.executemany("INSERT INTO llm_usage(at,cycle_id,label,model,input_tokens,output_tokens,usd) VALUES(?,?,?,?,?,?,?)",
                            [(now(), cycle_id, e["label"], e["model"], e["in"], e["out"], e["usd"]) for e in entries])
        self.db.commit()

    def spend_this_month_usd(self) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        llm = self.db.execute("SELECT COALESCE(SUM(usd),0) FROM llm_usage WHERE at LIKE ?", (month + "%",)).fetchone()[0]
        acts = self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM actions WHERE status='done' AND updated_at LIKE ?",
                               (month + "%",)).fetchone()[0]
        return float(llm) + float(acts)

    # ---- memory files -------------------------------------------------------------
    def read_memory(self, name: str) -> str:
        p = self.memory_dir / name
        return p.read_text() if p.exists() else ""

    def append_memory(self, name: str, text: str) -> None:
        p = self.memory_dir / name
        with p.open("a") as f:
            f.write(text.rstrip() + "\n")

    def write_output(self, relpath: str, text: str) -> Path:
        p = self.outputs_dir / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p
