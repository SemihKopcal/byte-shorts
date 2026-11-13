"""
SQLite (tek kullanicili panel icin yeterli, sunucu/ag yok = saldiri yuzeyi yok).

Her SQL parametreli; kullanici girdisi sorguya ASLA birlestirilmez. Yazma
islemleri `with db.tx():` icinde, BEGIN IMMEDIATE ile.
"""
from __future__ import annotations

import contextlib
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS videos(
  script_id     TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  series        TEXT NOT NULL DEFAULT '',
  duration      REAL NOT NULL DEFAULT 0,
  size_bytes    INTEGER NOT NULL DEFAULT 0,
  sha256        TEXT NOT NULL DEFAULT '',
  video_key     TEXT NOT NULL,
  manifest_key  TEXT NOT NULL,
  captions_key  TEXT NOT NULL,
  run_url       TEXT NOT NULL DEFAULT '',
  approval      TEXT NOT NULL DEFAULT 'pending'
                CHECK(approval IN ('pending','approved','rejected')),
  approved_at   TEXT,
  approved_by   TEXT,
  rendered_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL,
  files_deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS publications(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  script_id     TEXT NOT NULL REFERENCES videos(script_id),
  platform      TEXT NOT NULL CHECK(platform IN ('youtube','instagram','tiktok')),
  status        TEXT NOT NULL DEFAULT 'planned'
                CHECK(status IN ('planned','dispatched','published','failed','canceled')),
  scheduled_at  TEXT NOT NULL,
  request_id    TEXT,
  dispatched_at TEXT,
  finished_at   TEXT,
  remote_id     TEXT,
  remote_url    TEXT,
  error         TEXT,
  attempts      INTEGER NOT NULL DEFAULT 0,
  UNIQUE(script_id, platform)
);
CREATE INDEX IF NOT EXISTS pub_due ON publications(status, scheduled_at);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS script_requests(
  request_id  TEXT PRIMARY KEY,
  action      TEXT NOT NULL CHECK(action IN ('ingest','move_first','remove')),
  script_id   TEXT NOT NULL DEFAULT '',
  title       TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'sent' CHECK(status IN ('sent','ok','rejected','error')),
  message     TEXT NOT NULL DEFAULT '',
  problems    TEXT NOT NULL DEFAULT '[]',
  form        TEXT NOT NULL DEFAULT '',
  actor       TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS sr_status ON script_requests(status, created_at);

CREATE TABLE IF NOT EXISTS audit(
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  at     TEXT NOT NULL,
  actor  TEXT NOT NULL,
  ip     TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class Db:
    def __init__(self, path: str):
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        for p in ("journal_mode=WAL", "foreign_keys=ON", "busy_timeout=5000",
                  "secure_delete=ON", "trusted_schema=OFF"):
            self.conn.execute(f"PRAGMA {p}")
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema',?)",
                          (str(SCHEMA_VERSION),))

    @contextlib.contextmanager
    def tx(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            else:
                self.conn.execute("COMMIT")

    def one(self, sql: str, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchone()

    def all(self, sql: str, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def run(self, sql: str, args=()):
        with self._lock:
            return self.conn.execute(sql, args)

    def close(self):
        with self._lock:
            self.conn.close()

    def __del__(self):
        try:
            self.conn.close()
        except Exception:
            pass
