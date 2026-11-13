"""经用户确认的动作收据；与模型消息分离，跨进程防止重复执行。"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


class ActionStore:
    def __init__(self, path: str | Path | None = None):
        root = Path(__file__).resolve().parents[2]
        self.path = Path(path or os.getenv("FINSIGHT_ACTION_STORE", str(root / "data/runtime_actions.sqlite")))

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.execute("CREATE TABLE IF NOT EXISTS runtime_actions (owner TEXT, run_id TEXT, action_id TEXT, payload TEXT, PRIMARY KEY(owner,run_id,action_id))")
        return conn

    def propose(self, owner: str, run_id: str, action: dict) -> dict:
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO runtime_actions VALUES (?,?,?,?)",
                         (owner, run_id, action["action_id"], json.dumps(action, ensure_ascii=False)))
            row = conn.execute("SELECT payload FROM runtime_actions WHERE owner=? AND run_id=? AND action_id=?",
                               (owner, run_id, action["action_id"])).fetchone()
            return json.loads(row[0])

    def claim(self, owner: str, run_id: str, action_id: str, payload_hash: str, confirmed: bool) -> tuple[dict, bool]:
        import time
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM runtime_actions WHERE owner=? AND run_id=? AND action_id=?",
                               (owner, run_id, action_id)).fetchone()
            if row is None:
                raise ValueError("action_not_found")
            action = json.loads(row[0])
            if action["payload_hash"] != payload_hash:
                raise ValueError("action_not_found")
            if action["status"] != "proposed":
                return action, False
            action["status"] = "expired" if action["expires_at"] < time.time() else ("executing" if confirmed else "cancelled")
            conn.execute("UPDATE runtime_actions SET payload=? WHERE owner=? AND run_id=? AND action_id=?",
                         (json.dumps(action, ensure_ascii=False), owner, run_id, action_id))
            return action, action["status"] == "executing"

    def finish(self, owner: str, run_id: str, action: dict) -> dict:
        with self.connect() as conn:
            conn.execute("UPDATE runtime_actions SET payload=? WHERE owner=? AND run_id=? AND action_id=?",
                         (json.dumps(action, ensure_ascii=False), owner, run_id, action["action_id"]))
        return action

