import hashlib
import secrets
import sqlite3
import uuid

from common.logger import get_logger
from database.config import SQLiteDBConfig

logging = get_logger(__name__)

_PBKDF2_ITERATIONS = 240_000
_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # RFC 4122 namespace


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random salt: pbkdf2_sha256$iters$salt$hash."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return secrets.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def derive_oid(username: str) -> str:
    """Stable per-user uuid5, preserving the oid semantics of the old Entra ids."""
    return str(uuid.uuid5(_UUID_NAMESPACE, f"user:{username}"))


def get_user(username: str) -> dict | None:
    conn: sqlite3.Connection = SQLiteDBConfig().connect()
    try:
        row = conn.execute(
            "SELECT username, password_hash, display_name, oid FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def count_users() -> int:
    conn: sqlite3.Connection = SQLiteDBConfig().connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def create_user(username: str, password: str, display_name: str = "") -> None:
    conn: sqlite3.Connection = SQLiteDBConfig().connect()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, oid) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), display_name or username, derive_oid(username)),
        )
        conn.commit()
        logging.info(f"User '{username}' created.")
    except sqlite3.IntegrityError:
        logging.warning(f"User '{username}' already exists; skipped.")
    finally:
        conn.close()


def ensure_bootstrap_user() -> None:
    """Create the admin account only when the users table is empty (first boot)."""
    from config.config import settings

    if count_users() == 0:
        create_user(settings.admin_username, settings.admin_password, "Administrator")
        logging.info(
            "Bootstrap admin account created. Change ADMIN_PASSWORD before exposing this service."
        )
