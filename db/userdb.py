import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("USER_DB_PATH", "userdb.sqlite3")


# Simple email validation pattern
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _validate_email(email: str) -> str:
    """Validate and return a sanitized email, or raise ValueError."""
    if not email or not isinstance(email, str):
        raise ValueError("Email is required")
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise ValueError("Invalid email address")
    return email


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                ai_count INTEGER DEFAULT 0,
                last_ai_reset TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.commit()


def get_user(email):
    """Get user by email."""
    email = _validate_email(email)
    with get_db() as db:
        cur = db.execute("SELECT * FROM users WHERE email = ?", (email,))
        return cur.fetchone()


def get_user_by_id(user_id):
    """Get user by ID."""
    with get_db() as db:
        cur = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()


def create_user(email):
    """Create a new user or return existing one."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            "INSERT OR IGNORE INTO users (email, ai_count, last_ai_reset) VALUES (?, 0, ?)",
            (email, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()
        return get_user(email)


def increment_ai_count(email):
    email = _validate_email(email)
    with get_db() as db:
        db.execute("UPDATE users SET ai_count = ai_count + 1 WHERE email = ?", (email,))
        db.commit()


def reset_ai_count(email):
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            "UPDATE users SET ai_count = 0, last_ai_reset = ? WHERE email = ?",
            (datetime.now(timezone.utc).isoformat(), email),
        )
        db.commit()


def should_reset_ai(email):
    user = get_user(email)
    if not user or not user["last_ai_reset"]:
        return True
    last = datetime.fromisoformat(user["last_ai_reset"])
    # Ensure timezone-aware comparison
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last) > timedelta(days=1)


# Initialize database only when this module is the entry point,
# or call init_db() explicitly from your app setup.
if __name__ == "__main__":
    init_db()
