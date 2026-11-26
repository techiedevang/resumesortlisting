"""
database.py
-----------
Thin SQLite persistence layer. Uses raw sqlite3 (stdlib only, no ORM
dependency) with a small connection-per-call helper. For a larger
production system this would move to SQLAlchemy + Postgres, but the
query surface here is intentionally small enough that raw SQL stays
readable and the whole app remains a single `pip install` away from
running anywhere.

A candidate's decision (selected / under review / rejected) is not stored as
a fact. It is computed from the score and the job's two thresholds each time
it is read, unless a recruiter has overridden it. What the candidate was last
told is stored separately (`notified_status`).
"""

import json
import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import bands

DB_PATH = os.environ.get(
    "SCREENING_DB",
    os.path.join(os.path.dirname(__file__), "..", "screening.db"),
)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release. init_db() adds any that an older
# database file is missing, so existing data keeps working.
_MIGRATIONS = {
    "jobs": [
        ("select_threshold", f"REAL NOT NULL DEFAULT {bands.DEFAULT_SELECT_AT}"),
        ("review_threshold", f"REAL NOT NULL DEFAULT {bands.DEFAULT_REVIEW_AT}"),
    ],
    "candidates": [
        ("profile", "TEXT NOT NULL DEFAULT '{}'"),
        ("depth_score", "REAL NOT NULL DEFAULT 0"),
        ("evidence", "TEXT NOT NULL DEFAULT '{}'"),
        ("email", "TEXT NOT NULL DEFAULT ''"),
        ("reference", "TEXT NOT NULL DEFAULT ''"),
        ("status_override", "TEXT NOT NULL DEFAULT ''"),
        ("notified_status", "TEXT NOT NULL DEFAULT ''"),
        ("notified_at", "TEXT NOT NULL DEFAULT ''"),
    ],
}


def init_db():
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                filename TEXT NOT NULL,
                resume_text TEXT NOT NULL,
                similarity_score REAL NOT NULL,
                skill_coverage_score REAL NOT NULL,
                final_score REAL NOT NULL,
                matched_skills TEXT NOT NULL,
                missing_skills TEXT NOT NULL,
                extra_skills TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_job_id
                ON candidates (job_id);

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL,
                to_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                mode TEXT NOT NULL,
                delivery TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (candidate_id) REFERENCES candidates (id) ON DELETE CASCADE
            );
            """
        )
        for table, columns in _MIGRATIONS.items():
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, ddl in columns:
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_reference ON candidates (reference)"
        )


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- Jobs ----

def create_job(title: str, description: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (title, description, created_at) VALUES (?, ?, ?)",
            (title, description, _now()),
        )
        return cur.lastrowid


def get_job(job_id: int):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT j.*, COUNT(c.id) AS candidate_count
            FROM jobs j
            LEFT JOIN candidates c ON c.job_id = j.id
            GROUP BY j.id
            ORDER BY j.created_at DESC, j.id DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def update_job_thresholds(job_id: int, select_at: float, review_at: float):
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET select_threshold = ?, review_threshold = ? WHERE id = ?",
            (float(select_at), float(review_at), job_id),
        )


def delete_job(job_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


# --------------------------------------------------------- Candidates ----

def _new_reference(conn) -> str:
    for _ in range(10):
        ref = "SCR-" + secrets.token_hex(3).upper()
        if not conn.execute("SELECT 1 FROM candidates WHERE reference = ?", (ref,)).fetchone():
            return ref
    raise RuntimeError("Could not allocate a unique reference.")


def create_candidate(job_id: int, name: str, filename: str, resume_text: str,
                     match_result, profile: dict = None, email: str = "") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO candidates (
                job_id, name, filename, resume_text,
                similarity_score, skill_coverage_score, depth_score, final_score,
                matched_skills, missing_skills, extra_skills,
                profile, evidence, email, reference, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, name, filename, resume_text,
                match_result.similarity_score,
                match_result.skill_coverage_score,
                match_result.depth_score,
                match_result.final_score,
                json.dumps(match_result.matched_skills),
                json.dumps(match_result.missing_skills),
                json.dumps(match_result.extra_skills),
                json.dumps(profile or {}),
                json.dumps(match_result.evidence()),
                email,
                _new_reference(conn),
                _now(),
            ),
        )
        return cur.lastrowid


def _deserialise_candidate(row: dict) -> dict:
    for key in ("matched_skills", "missing_skills", "extra_skills"):
        row[key] = json.loads(row[key])
    row["profile"] = json.loads(row.get("profile") or "{}")
    row["evidence"] = json.loads(row.get("evidence") or "{}")

    select_at = row.pop("select_threshold", bands.DEFAULT_SELECT_AT)
    review_at = row.pop("review_threshold", bands.DEFAULT_REVIEW_AT)
    row["suggested_status"] = bands.decide(row["final_score"], select_at, review_at)
    row["status"] = row["status_override"] or row["suggested_status"]
    row["status_source"] = "recruiter" if row["status_override"] else "score"
    row["flags"] = row["evidence"].get("flags", [])
    return row


_LIST_COLUMNS = """
    c.id, c.job_id, c.name, c.filename, c.email, c.reference,
    c.similarity_score, c.skill_coverage_score, c.depth_score, c.final_score,
    c.matched_skills, c.missing_skills, c.extra_skills, c.profile, c.evidence,
    c.status_override, c.notified_status, c.notified_at, c.created_at,
    j.select_threshold, j.review_threshold
"""


def list_candidates_for_job(job_id: int):
    """Candidates best first, each with `rank` and `top_percent`."""
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT {_LIST_COLUMNS}
            FROM candidates c JOIN jobs j ON j.id = c.job_id
            WHERE c.job_id = ?
            ORDER BY c.final_score DESC, c.id ASC
            """,
            (job_id,),
        ).fetchall()
    out = [_deserialise_candidate(dict(r)) for r in rows]
    total = len(out)
    for i, c in enumerate(out, start=1):
        c["rank"] = i
        c["top_percent"] = math.ceil(i / total * 100)
    return out


def get_candidate(candidate_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.*, j.select_threshold, j.review_threshold, j.title AS job_title
            FROM candidates c JOIN jobs j ON j.id = c.job_id
            WHERE c.id = ?
            """,
            (candidate_id,),
        ).fetchone()
        if not row:
            return None
        cand = _deserialise_candidate(dict(row))
        ahead = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE job_id = ? AND final_score > ?",
            (cand["job_id"], cand["final_score"]),
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE job_id = ?", (cand["job_id"],)
        ).fetchone()[0]
    cand["rank"] = ahead + 1
    cand["top_percent"] = math.ceil(cand["rank"] / total * 100)
    cand["job_candidate_count"] = total
    return cand


def set_status_override(candidate_id: int, status: str):
    """status is one of bands.STATUSES, or '' to return to the score's decision."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE candidates SET status_override = ? WHERE id = ?",
            (status, candidate_id),
        )


def mark_notified(candidate_id: int, status: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE candidates SET notified_status = ?, notified_at = ? WHERE id = ?",
            (status, _now(), candidate_id),
        )


def delete_candidate(candidate_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,))


def find_application(email: str, reference: str):
    """Look up one application for the candidate status page, or None."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.id, c.name, c.notified_status, c.notified_at, j.title AS job_title
            FROM candidates c JOIN jobs j ON j.id = c.job_id
            WHERE c.reference = ? AND lower(c.email) = lower(?)
            """,
            (reference.strip().upper(), email.strip()),
        ).fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------ Messages ----

def create_message(candidate_id: int, to_email: str, subject: str, body: str,
                   mode: str, delivery: str, error: str, status: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (candidate_id, to_email, subject, body, mode,
                                  delivery, error, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (candidate_id, to_email, subject, body, mode, delivery, error, status, _now()),
        )
        return cur.lastrowid


def list_messages(limit: int = 100):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.*, c.name AS candidate_name, j.title AS job_title
            FROM messages m
            JOIN candidates c ON c.id = m.candidate_id
            JOIN jobs j ON j.id = c.job_id
            ORDER BY m.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------- Users ----

def count_users() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username: str, password_hash: str) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, _now()),
        )
        return cur.lastrowid


def get_user(username: str):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?)", (username,)
        ).fetchone()
        return dict(row) if row else None
