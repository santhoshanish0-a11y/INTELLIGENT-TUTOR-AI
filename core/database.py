"""
Persistence layer.

  * Default: SQLite, one file called tutor.db (standard library only). Nothing to install or set up.
  * Optional: set DATABASE_URL in .env to a PostgreSQL address (for example from Supabase) and the very same
    tables are created and used there instead. Remove the line to go back to tutor.db.
The rest of the app only calls query(), execute() and now(), so it does not know which one is in use.
"""
import contextlib
import os
import re
import sqlite3
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("TUTOR_DB", os.path.join(ROOT, "tutor.db"))
DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
USING_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    exam TEXT NOT NULL DEFAULT 'GENERAL',
    created INTEGER NOT NULL,
    password_hash TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created INTEGER NOT NULL,
    expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    exam TEXT NOT NULL,
    subject TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL,
    finished INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_id INTEGER,
    question_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    subject TEXT,
    created INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, created);
"""


SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    exam TEXT NOT NULL DEFAULT 'GENERAL',
    created BIGINT NOT NULL,
    password_hash TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL,
    created BIGINT NOT NULL,
    expires BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    mode TEXT NOT NULL,
    exam TEXT NOT NULL,
    subject TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    created BIGINT NOT NULL,
    finished INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attempts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    session_id BIGINT,
    question_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    topic TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
    created BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_log (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    intent TEXT,
    subject TEXT,
    created BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempts_user ON attempts(user_id, created);
"""

# Columns added after the first release. Older tutor.db files get them automatically, keeping all progress.
_USER_COLUMNS = {
    "password_hash": "TEXT",
    "failed_attempts": "INTEGER NOT NULL DEFAULT 0",
    "locked_until": "INTEGER NOT NULL DEFAULT 0",
}


# --------------------------------------------------------------------------- #
# SQLite (default)
# --------------------------------------------------------------------------- #
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------------- #
# PostgreSQL (only when DATABASE_URL is set)
# --------------------------------------------------------------------------- #
def _pg_sql(sql):
    """The app writes SQL with ? placeholders (SQLite style). PostgreSQL drivers use %s."""
    return sql.replace("%", "%%").replace("?", "%s")


_NO_ID_TABLES = re.compile(r"^\s*INSERT\s+INTO\s+sessions\b", re.I)   # this table has no id column


@contextlib.contextmanager
def _pg_conn():
    import psycopg2
    import psycopg2.extras
    kwargs = {"connect_timeout": 10, "cursor_factory": psycopg2.extras.RealDictCursor}
    if "sslmode" not in DATABASE_URL:
        kwargs["sslmode"] = "require"
    conn = psycopg2.connect(DATABASE_URL, **kwargs)
    try:
        with conn:                      # commits on success, rolls back on error
            yield conn
    finally:
        conn.close()


def init_db():
    if USING_POSTGRES:
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute(SCHEMA_PG)
        return
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        have = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for column, ddl in _USER_COLUMNS.items():
            if column not in have:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")


def query(sql, args=(), one=False):
    if USING_POSTGRES:
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute(_pg_sql(sql), tuple(args))
            rows = [dict(r) for r in cur.fetchall()]
    else:
        with get_conn() as conn:
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()):
    """Run one INSERT/UPDATE/DELETE. For an INSERT, returns the new row's id."""
    if USING_POSTGRES:
        is_insert = sql.lstrip().upper().startswith("INSERT")
        returning = is_insert and not _NO_ID_TABLES.match(sql)
        with _pg_conn() as conn, conn.cursor() as cur:
            cur.execute(_pg_sql(sql) + (" RETURNING id" if returning else ""), tuple(args))
            return cur.fetchone()["id"] if returning else None
    with get_conn() as conn:
        cur = conn.execute(sql, args)
        return cur.lastrowid


def now():
    return int(time.time())


def backend():
    return "PostgreSQL (Supabase)" if USING_POSTGRES else "SQLite (tutor.db)"