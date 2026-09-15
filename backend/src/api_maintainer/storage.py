import sqlite3
import time
from contextlib import contextmanager

from .schema import Report
from .status import apply_result


class BusyError(RuntimeError):
    pass


class StateError(RuntimeError):
    pass


class Store:
    def __init__(self, root):
        root = root.resolve()
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "runs.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, report TEXT NOT NULL, key TEXT UNIQUE, fingerprint TEXT);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, kind TEXT, message TEXT, at REAL);
                CREATE TABLE IF NOT EXISTS lease(singleton INTEGER PRIMARY KEY CHECK(singleton=1), run TEXT, pid INTEGER, heartbeat REAL, kind TEXT);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(lease)")}
            if "worker_pid" not in columns:
                db.execute("ALTER TABLE lease ADD COLUMN worker_pid INTEGER")
            # Events gained stage/status/duration so a log line says which agent
            # acted and whether it worked. Older rows keep NULLs and read as "info".
            columns = {r[1] for r in db.execute("PRAGMA table_info(events)")}
            for name, kind in (("stage", "TEXT"), ("status", "TEXT"), ("duration_ms", "INTEGER")):
                if name not in columns:
                    db.execute(f"ALTER TABLE events ADD COLUMN {name} {kind}")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, run_id):
        with self.connection() as db:
            row = db.execute("SELECT report FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Unknown run.")
        return apply_result(Report.model_validate_json(row["report"]))

    def save(self, report):
        apply_result(report)
        with self.connection() as db:
            db.execute("UPDATE runs SET report=? WHERE id=?", (report.model_dump_json(), report.run_id))

    def recent(self, limit=100):
        with self.connection() as db:
            rows = db.execute("SELECT report FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        # Re-derive the verdict so history never shows a stale result for a row
        # written before the run reached its final lifecycle.
        return [apply_result(Report.model_validate_json(r["report"])).model_dump() for r in rows]

    def event(self, run, kind, message, stage=None, status="info", duration_ms=None):
        with self.connection() as db:
            db.execute(
                "INSERT INTO events(run,kind,message,at,stage,status,duration_ms) VALUES(?,?,?,?,?,?,?)",
                (run, kind, message[:2000], time.time(), stage, status, duration_ms),
            )

    def events(self, run, after=0, limit=100):
        self.get(run)
        with self.connection() as db:
            return [
                {**dict(row), "status": row["status"] or "info"}
                for row in db.execute(
                    "SELECT seq,kind,message,at,stage,status,duration_ms FROM events"
                    " WHERE run=? AND seq>? ORDER BY seq LIMIT ?",
                    (run, after, limit),
                )
            ]

    def claim(self, run_id, stage):
        with self.connection() as db:
            row = db.execute("SELECT report FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError("Unknown run.")
            report = Report.model_validate_json(row["report"])
            if stage == "repairing" and report.lifecycle in ("repairing", "finalizing", "finished"):
                return False
            expected = "awaiting_review" if stage == "repairing" else "created"
            if stage != "evaluation" and report.lifecycle != expected:
                raise StateError("Run is not ready for this action.")
            if stage == "evaluation" and report.lifecycle != "finished":
                raise StateError("Only finished migrations can be evaluated.")
            if db.execute("SELECT 1 FROM lease").fetchone():
                raise BusyError("Another migration or evaluation is executing. Try again when it finishes.")
            db.execute(
                "INSERT INTO lease(singleton,run,pid,heartbeat,kind) VALUES(1,?,NULL,?,?)",
                (run_id, time.time(), stage),
            )
            if stage != "evaluation":
                report.lifecycle = stage
                db.execute("UPDATE runs SET report=? WHERE id=?", (report.model_dump_json(), run_id))
            return True

    def leased(self, run_id):
        with self.connection() as db:
            return bool(db.execute("SELECT 1 FROM lease WHERE run=?", (run_id,)).fetchone())

    def heartbeat(self, run_id, pid):
        with self.connection() as db:
            db.execute("UPDATE lease SET pid=?,heartbeat=? WHERE run=?", (pid, time.time(), run_id))

    def set_worker(self, run_id, pid):
        with self.connection() as db:
            db.execute("UPDATE lease SET worker_pid=? WHERE run=?", (pid, run_id))

    def release(self, run_id):
        with self.connection() as db:
            db.execute("DELETE FROM lease WHERE run=?", (run_id,))
