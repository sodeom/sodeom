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
                is_pro INTEGER DEFAULT 0,
                ai_count INTEGER DEFAULT 0,
                last_ai_reset TEXT,
                stripe_customer_id TEXT,
                subscription_id TEXT,
                subscription_status TEXT,
                subscription_type TEXT,
                pro_expires_at TEXT,
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
            "INSERT OR IGNORE INTO users (email, is_pro, ai_count, last_ai_reset) VALUES (?, 0, 0, ?)",
            (email, datetime.now(timezone.utc).isoformat()),
        )
        db.commit()
        return get_user(email)


def set_pro(email):
    """Set user as Pro by email."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            "UPDATE users SET is_pro = 1, updated_at = ? WHERE email = ?",
            (datetime.now(timezone.utc).isoformat(), email),
        )
        db.commit()


def set_pro_by_id(user_id):
    """Set user as Pro by ID."""
    if not isinstance(user_id, int) or user_id < 1:
        raise ValueError("Invalid user ID")
    with get_db() as db:
        db.execute(
            "UPDATE users SET is_pro = 1, updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), user_id),
        )
        db.commit()


def update_stripe_info(
    email,
    customer_id=None,
    subscription_id=None,
    subscription_status=None,
    subscription_type=None,
):
    """Update Stripe customer and subscription info for a user."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            """UPDATE users SET
               stripe_customer_id = COALESCE(?, stripe_customer_id),
               subscription_id = COALESCE(?, subscription_id),
               subscription_status = COALESCE(?, subscription_status),
               subscription_type = COALESCE(?, subscription_type),
               updated_at = ?
               WHERE email = ?""",
            (
                customer_id,
                subscription_id,
                subscription_status,
                subscription_type,
                datetime.now(timezone.utc).isoformat(),
                email,
            ),
        )
        db.commit()


def set_subscription(email, subscription_id, subscription_type, expires_at=None):
    """Set subscription info for a user."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            """UPDATE users SET
               is_pro = 1,
               subscription_id = ?,
               subscription_type = ?,
               subscription_status = 'active',
               pro_expires_at = ?,
               updated_at = ?
               WHERE email = ?""",
            (
                subscription_id,
                subscription_type,
                expires_at,
                datetime.now(timezone.utc).isoformat(),
                email,
            ),
        )
        db.commit()


def cancel_subscription(email):
    """Cancel a user's subscription (keep Pro until end of period)."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            """UPDATE users SET
               subscription_status = 'cancelled',
               updated_at = ?
               WHERE email = ?""",
            (datetime.now(timezone.utc).isoformat(), email),
        )
        db.commit()


def expire_pro(email):
    """Remove Pro status from a user."""
    email = _validate_email(email)
    with get_db() as db:
        db.execute(
            "UPDATE users SET is_pro = 0, subscription_status = 'expired', updated_at = ? WHERE email = ?",
            (datetime.now(timezone.utc).isoformat(), email),
        )
        db.commit()


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


def get_all_pro_users():
    """Get all Pro users (for admin purposes)."""
    with get_db() as db:
        cur = db.execute("SELECT * FROM users WHERE is_pro = 1")
        return cur.fetchall()


def get_expiring_subscriptions(days=7):
    """Get subscriptions expiring within X days."""
    with get_db() as db:
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        cur = db.execute(
            "SELECT * FROM users WHERE is_pro = 1 AND pro_expires_at IS NOT NULL AND pro_expires_at <= ?",
            (cutoff,),
        )
        return cur.fetchall()


# Helper: Check if user has active Pro
def has_active_pro(user):
    return user["is_pro"] and user.get("subscription_status") in ("active", "lifetime")


# Initialize database only when this module is the entry point,
# or call init_db() explicitly from your app setup.
if __name__ == "__main__":
    init_db()
