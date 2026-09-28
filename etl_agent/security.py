"""Password and opaque session token rules shared by CLI and API."""

import hashlib
import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher

hasher = PasswordHasher()


@lru_cache(maxsize=1)
def weak_passwords() -> frozenset[str]:
    path = Path(__file__).with_name("weak_passwords_v1.txt")
    words = frozenset(line.strip().casefold() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if len(words) < 100:
        raise RuntimeError("Offline password blocklist is missing or incomplete")
    return words


def validate_password(password: str, username: str, project_names: list[str]) -> None:
    if len(password) < 15:
        raise ValueError("Password must contain at least 15 characters")
    lowered = password.casefold()
    if lowered in weak_passwords():
        raise ValueError("Password is on the offline weak-password list")
    if any(len(term) >= 3 and term in lowered for term in [username.casefold(), *(name.casefold() for name in project_names)]):
        raise ValueError("Password contains account or project context")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
