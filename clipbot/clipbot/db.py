"""SQLite store for clips and worker status."""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    broadcaster TEXT, title TEXT, url TEXT, view_count INTEGER,
    created_at TEXT, status TEXT, raw_path TEXT, edited_path TEXT,
    yt_id TEXT, ig_id TEXT, voice_path TEXT, vertical_path TEXT,
    transcript TEXT, script TEXT, error TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""
# status flow: new -> [needs_script -> script_ready -> voice_ready ->] pending_review|approved -> published | failed | rejected


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(clips)")}
        for col in ("voice_path", "vertical_path", "transcript", "script"):
            if col not in cols:
                self.conn.execute(f"ALTER TABLE clips ADD COLUMN {col} TEXT")

    def add_clip(self, c: dict) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO clips (id, broadcaster, title, url, view_count, created_at, status, updated_at)"
            " VALUES (?,?,?,?,?,?, 'new', ?)",
            (c["id"], c["broadcaster_name"], c["title"], c["url"], c["view_count"], c["created_at"], now()))
        self.conn.commit()
        return cur.rowcount == 1

    def update(self, clip_id: str, **fields):
        fields["updated_at"] = now()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE clips SET {sets} WHERE id=?", (*fields.values(), clip_id))
        self.conn.commit()

    def by_status(self, status: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM clips WHERE status=? ORDER BY view_count DESC", (status,)).fetchall()

    def all(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM clips ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()

    def posted_last_24h(self, column: str) -> int:
        assert column in ("yt_id", "ig_id")
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        return self.conn.execute(
            f"SELECT COUNT(*) FROM clips WHERE {column} IS NOT NULL AND updated_at >= ?", (since,)).fetchone()[0]

    def counts(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute("SELECT status, COUNT(*) FROM clips GROUP BY status")}

    def set_kv(self, k: str, v: str):
        self.conn.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, v))
        self.conn.commit()

    def get_kv(self, k: str, default: str = "") -> str:
        r = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else default
