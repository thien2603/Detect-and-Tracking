import json
import logging
import sqlite3
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread

import cv2

LOGGER = logging.getLogger(__name__)


class EventRepository:
    def __init__(self, path, snapshot_dir):
        self.path, self.snapshot_dir = Path(path), Path(snapshot_dir)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id TEXT PRIMARY KEY, occurred_at TEXT, camera_id TEXT, "
            "event_type TEXT, payload TEXT NOT NULL)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS events_camera_time ON events(camera_id, occurred_at)"
        )
        self.connection.commit()

    def save(self, event, frame):
        # A retry of the same persisted candidate is idempotent. Separate genuine
        # entry/re-entry occurrences still have distinct candidate IDs.
        with self.lock:
            if self.connection.execute("SELECT 1 FROM events WHERE id=?", (event.id,)).fetchone():
                return False
            target = self.snapshot_dir / f"{event.id}.jpg"
            if not cv2.imwrite(str(target), frame):
                raise OSError(f"Snapshot write failed: {target}")
            event.snapshot = str(target.resolve())
            with self.connection:
                self.connection.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.occurred_at,
                        event.camera_id,
                        event.event_type,
                        json.dumps(event.to_dict()),
                    ),
                )
        return True

    def query(self, camera_id=None, start=None, end=None, limit=100):
        where, args = [], []
        for column, op, value in (
            ("camera_id", "=", camera_id),
            ("occurred_at", ">=", start),
            ("occurred_at", "<=", end),
        ):
            if value is not None:
                where.append(f"{column} {op} ?")
                args.append(value)
        sql = "SELECT payload FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        with self.lock:
            rows = self.connection.execute(sql, [*args, limit]).fetchall()
        return [json.loads(row[0]) for row in rows]

    def snapshot_for(self, event_id):
        with self.lock:
            row = self.connection.execute(
                "SELECT payload FROM events WHERE id=?", (event_id,)
            ).fetchone()
        return json.loads(row[0]).get("snapshot") if row else None

    def close(self):
        with self.lock:
            self.connection.close()


class EventWriter:
    """Bounded evidence queue; explicit drop/error metrics instead of silent loss."""

    def __init__(self, repository, capacity=64):
        self.repository = repository
        self.queue = Queue(maxsize=capacity)
        self.dropped = 0
        self.failed = 0
        self.thread = Thread(target=self._run, name="evidence", daemon=True)
        self.thread.start()

    def submit(self, event, frame):
        try:
            self.queue.put_nowait((event, frame.copy()))
        except Full:
            self.dropped += 1
            LOGGER.warning("Evidence queue full; dropped event %s", event.id)

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                self.repository.save(*item)
            except Exception:
                self.failed += 1
                LOGGER.exception("Evidence persistence failed")
            finally:
                self.queue.task_done()

    def close(self):
        if not self.thread.is_alive():
            return
        # Drain pending events; never close the database before this thread exits.
        self.queue.put(None)
        self.thread.join()
