"""
auth.py
-------
Recruiter accounts and a small in-memory rate limiter.

Passwords are stored as salted hashes (werkzeug's scrypt/pbkdf2). The first
account is created from the login page while no account exists; after that,
the page only signs in. The limiter keeps its counts in process memory, so it
resets on restart and is per worker: fine for one server, and the place to
swap in Redis for several.
"""

import re
import time
from collections import defaultdict, deque

from werkzeug.security import check_password_hash, generate_password_hash

MIN_PASSWORD = 8
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def validate_new_account(username: str, password: str):
    """Return an error message, or None when the pair is acceptable."""
    if not _USERNAME.match(username or ""):
        return "Username must be 3 to 32 letters, digits, dots, dashes or underscores."
    if len(password or "") < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters."
    if password.lower() == username.lower():
        return "Password must not be the same as the username."
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    return check_password_hash(stored_hash, password or "")


class RateLimiter:
    """Allow at most `limit` events per `window` seconds for each key."""

    def __init__(self, limit: int, window: float, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._events = defaultdict(deque)

    def _trim(self, key):
        q, cutoff = self._events[key], self.clock() - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        return q

    def blocked(self, key) -> bool:
        return len(self._trim(key)) >= self.limit

    def record(self, key):
        self._trim(key).append(self.clock())

    def reset(self, key):
        self._events.pop(key, None)

    def retry_after(self, key) -> int:
        q = self._trim(key)
        return max(1, int(q[0] + self.window - self.clock()) + 1) if q else 0
