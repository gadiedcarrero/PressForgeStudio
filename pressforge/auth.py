"""Autenticación simple (BYOK self-hosted).

Una contraseña de administrador por instancia. En el primer arranque el usuario
la crea; luego inicia sesión con ella. El hash (PBKDF2) se guarda en
`secrets.json` (local, gitignored). Las sesiones son tokens en memoria.

No usa dependencias externas (hashlib/secrets/hmac de la stdlib).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets as _secrets
import time

from . import secrets_store

_ITER = 200_000
_SESSION_TTL = 14 * 24 * 3600  # 14 días
_sessions: dict[str, float] = {}  # token -> expira (epoch)


# ─── Contraseña ───
def has_password() -> bool:
    return bool(secrets_store.get_secret("auth_hash"))


def set_password(password: str) -> None:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITER)
    secrets_store.set_secret("auth_salt", salt.hex())
    secrets_store.set_secret("auth_hash", h.hex())


def verify_password(password: str) -> bool:
    salt, stored = secrets_store.get_secret("auth_salt"), secrets_store.get_secret("auth_hash")
    if not salt or not stored:
        return False
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITER)
    return hmac.compare_digest(h.hex(), stored)


# ─── Sesiones ───
def new_session() -> str:
    token = _secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _SESSION_TTL
    return token


def valid_session(token: str) -> bool:
    exp = _sessions.get(token or "")
    if not exp:
        return False
    if exp < time.time():
        _sessions.pop(token, None)
        return False
    return True


def end_session(token: str) -> None:
    _sessions.pop(token or "", None)
