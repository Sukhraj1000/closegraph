"""Durable state and exclusive issue/path ownership."""
from __future__ import annotations
import contextlib
import fcntl
import json
from pathlib import Path
import sqlite3
import time


def overlaps(left, right):
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS claims (path TEXT PRIMARY KEY, owner TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at REAL, key TEXT, event TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, data TEXT);
        """)
        self.db.commit()
        # Repair older interrupted completions. Never free paused/active or
        # unknown owners; only a durably completed job can release its paths.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.executemany("DELETE FROM claims WHERE owner=?",
                                [(job["key"],) for job in self.jobs() if job["stage"] == "done"])

    @contextlib.contextmanager
    def controller_lock(self):
        with self.path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Another controller owns this state; use status to inspect it") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def jobs(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT data FROM jobs ORDER BY key")]

    def get(self, key):
        row = self.db.execute("SELECT data FROM jobs WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def event(self, key, event, data=None):
        self.db.execute("INSERT INTO events(at,key,event,data) VALUES(?,?,?,?)",
                        (time.time(), key, event, json.dumps(data)))
        self.db.commit()

    def save(self, job, event=None):
        self.db.execute("INSERT INTO jobs VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                        (job["key"], json.dumps(job, sort_keys=True)))
        self.db.commit()
        if event:
            self.event(job["key"], event, {"stage": job["stage"]})

    def claim(self, job, slots=3):
        if not 1 <= slots <= 3 or not job["paths"]:
            raise ValueError("Use 1..3 slots and explicit file ownership")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if self.get(job["key"]):
                self.db.rollback()
                return False
            active = sum(j["stage"] not in ("done", "paused") for j in self.jobs())
            held = list(self.db.execute("SELECT path,owner FROM claims"))
            if active >= slots or any(overlaps(p, h) for p in job["paths"] for h, _ in held):
                self.db.rollback()
                return False
            self.db.execute("INSERT INTO jobs VALUES(?,?)", (job["key"], json.dumps(job)))
            self.db.executemany("INSERT INTO claims VALUES(?,?)", [(p, job["key"]) for p in job["paths"]])
            self.db.commit()
            self.event(job["key"], "claimed", {"paths": job["paths"]})
            return True
        except BaseException:
            self.db.rollback()
            raise

    def complete(self, job):
        completed = dict(job, stage="done")
        # Do not call save/event: each commits separately. Completion, claim
        # release and its audit event are one crash-safe SQLite transaction.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("INSERT INTO jobs VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                            (job["key"], json.dumps(completed, sort_keys=True)))
            self.db.execute("DELETE FROM claims WHERE owner=?", (job["key"],))
            self.db.execute("INSERT INTO events(at,key,event,data) VALUES(?,?,?,?)",
                            (time.time(), job["key"], "completed", json.dumps({"stage": "done"})))
        job["stage"] = "done"  # In-memory state advances only after commit.

    def meta(self, key, value=None):
        if value is not None:
            self.db.execute("INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data",
                            (key, json.dumps(value)))
            self.db.commit()
        row = self.db.execute("SELECT data FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
