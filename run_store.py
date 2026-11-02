"""SQLite checkpoints; connections are short lived so Streamlit threads can share a store."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class RunStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL,
                lease_owner TEXT, lease_until REAL NOT NULL DEFAULT 0)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, state):
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,state,updated) VALUES (?,?,?)",
                       (state["run_id"], json.dumps(state, ensure_ascii=False), time.time()))

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT state FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("找不到该任务。")
        return json.loads(row[0])

    def acquire(self, run_id, seconds):
        owner, now = uuid.uuid4().hex, time.time()
        with self.connect() as db:
            result = db.execute("""UPDATE runs SET lease_owner=?, lease_until=?
                WHERE id=? AND (lease_owner IS NULL OR lease_until<?)""",
                                (owner, now + seconds, run_id, now))
            if result.rowcount != 1:
                raise RuntimeError("该任务正在执行；进程异常退出后，请待执行锁到期再恢复。")
        return owner

    def save(self, state, owner):
        with self.connect() as db:
            result = db.execute("UPDATE runs SET state=?,updated=? WHERE id=? AND lease_owner=?",
                                (json.dumps(state, ensure_ascii=False), time.time(), state["run_id"], owner))
            if result.rowcount != 1:
                raise RuntimeError("任务执行锁已失效。")

    def release(self, run_id, owner):
        with self.connect() as db:
            db.execute("UPDATE runs SET lease_owner=NULL,lease_until=0 WHERE id=? AND lease_owner=?",
                       (run_id, owner))

    def recent(self, limit=20):
        with self.connect() as db:
            rows = db.execute("SELECT state FROM runs ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]
