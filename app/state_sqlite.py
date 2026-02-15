import sqlite3
import json
import time
from typing import Dict, List, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS awards (
  user_id TEXT NOT NULL,
  achievement_id TEXT NOT NULL,
  awarded_at INTEGER NOT NULL,
  payload_json TEXT,
  PRIMARY KEY (user_id, achievement_id)
);
"""


class StateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def is_awarded(self, user_id: str, achievement_id: str) -> bool:
        with self._conn() as c:
            row = c.execute(
                "SELECT 1 FROM awards WHERE user_id=? AND achievement_id=?",
                (user_id, achievement_id),
            ).fetchone()
            return row is not None

    def record_awards(self, user_id: str, awards: List[Tuple[str, Dict]]) -> List[str]:
        """
        Records awards.
        If the payload dict contains '_timestamp', use that as the awarded_at time.
        Otherwise, use the current time.
        """
        default_now = int(time.time())
        inserted: List[str] = []

        with self._conn() as c:
            for achievement_id, payload in awards:
                # 1. Determine Timestamp
                award_ts = default_now

                # Check for override keys in the payload
                if isinstance(payload, dict):
                    if "_timestamp" in payload:
                        try:
                            award_ts = int(payload["_timestamp"])
                        except (ValueError, TypeError):
                            pass
                    # Fallback for 'date' or 'timestamp' if strictly integer
                    elif "timestamp" in payload and isinstance(payload["timestamp"], int):
                        award_ts = payload["timestamp"]

                # 2. Insert
                try:
                    c.execute(
                        "INSERT INTO awards(user_id, achievement_id, awarded_at, payload_json) VALUES(?,?,?,?)",
                        (user_id, achievement_id, award_ts, json.dumps(payload)),
                    )
                    inserted.append(achievement_id)
                except sqlite3.IntegrityError:
                    # Already exists (primary key collision)
                    pass

        return inserted

    def get_all_awards(self) -> List[Dict]:
        """Fetches all awards for the dashboard."""
        with self._conn() as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM awards ORDER BY awarded_at DESC").fetchall()
            awards = []
            for row in rows:
                d = dict(row)
                # Decode the JSON payload so the dashboard can use it
                if d.get("payload_json"):
                    try:
                        d["payload"] = json.loads(d["payload_json"])
                    except json.JSONDecodeError:
                        d["payload"] = {}
                awards.append(d)
            return awards