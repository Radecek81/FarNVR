"""Users, password hashing (Argon2), optional TOTP and login sessions."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .db import Database

COOKIE = "nvr_session"
_ph = PasswordHasher()
_DUMMY_HASH = _ph.hash("timing-equaliser")


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Heslo musí mít alespoň 10 znaků")
    return _ph.hash(password)


def create_user(db: Database, username: str, password: str, totp: bool = False) -> str | None:
    secret = pyotp.random_base32() if totp else None
    db.execute("INSERT INTO users(username, password_hash, totp_secret, created) VALUES (?,?,?,?)",
               (username.strip().lower(), hash_password(password), secret, time.time()))
    return secret


def set_password(db: Database, user_id: int, password: str) -> None:
    db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))
    db.execute("DELETE FROM login_sessions WHERE user_id=?", (user_id,))


def verify_login(db: Database, username: str, password: str, otp: str | None) -> tuple[int | None, str]:
    """Returns (user_id, error_code)."""
    row = db.one("SELECT id, password_hash, totp_secret FROM users WHERE username=?",
                 (username.strip().lower(),))
    try:
        _ph.verify(row["password_hash"] if row else _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        return None, "invalid"
    if not row:
        return None, "invalid"
    if row["totp_secret"]:
        if not otp:
            return None, "otp_required"
        if not pyotp.TOTP(row["totp_secret"]).verify(otp.strip(), valid_window=1):
            return None, "invalid_otp"
    if _ph.check_needs_rehash(row["password_hash"]):
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (_ph.hash(password), row["id"]))
    return row["id"], ""


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Database, user_id: int, days: int, ip: str, ua: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("INSERT INTO login_sessions(token_hash, user_id, created, expires, ip, user_agent) VALUES (?,?,?,?,?,?)",
               (_hash_token(token), user_id, now, now + days * 86400, ip, ua[:200]))
    return token


def session_user(db: Database, token: str | None, days: int) -> dict | None:
    if not token:
        return None
    th = _hash_token(token)
    row = db.one("SELECT u.id, u.username, u.totp_secret, s.expires FROM login_sessions s "
                 "JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (th,))
    now = time.time()
    if not row or row["expires"] < now:
        return None
    # sliding expiration, refreshed at most once per hour
    new_exp = now + days * 86400
    if new_exp - row["expires"] > 3600:
        db.execute("UPDATE login_sessions SET expires=? WHERE token_hash=?", (new_exp, th))
    return {"id": row["id"], "username": row["username"], "totp": bool(row["totp_secret"])}


def delete_session(db: Database, token: str | None) -> None:
    if token:
        db.execute("DELETE FROM login_sessions WHERE token_hash=?", (_hash_token(token),))


class RateLimiter:
    """Simple in-memory brute-force protection."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        q = self._hits[key]
        now = time.monotonic()
        while q and q[0] < now - self.window:
            q.popleft()
        return len(q) >= self.limit

    def hit(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)
