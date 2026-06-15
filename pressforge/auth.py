"""Autenticación simple (BYOK self-hosted).

Una contraseña de administrador por instancia. En el primer arranque el usuario
la crea; luego inicia sesión con ella. El hash (PBKDF2) se guarda en
`secrets.json` (local, gitignored). Las sesiones son tokens en memoria.

No usa dependencias externas (hashlib/secrets/hmac de la stdlib).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as _secrets
import time

from . import secrets_store

_ITER = 200_000
_SESSION_TTL = 14 * 24 * 3600  # 14 días


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


# ─── Sesiones (token firmado, sobrevive reinicios del servidor) ───
def _session_secret() -> bytes:
    """Secreto para firmar sesiones; se genera una vez y persiste en secrets.json."""
    s = secrets_store.get_secret("session_secret")
    if not s:
        s = _secrets.token_urlsafe(32)
        secrets_store.set_secret("session_secret", s)
    return s.encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_session() -> str:
    payload = json.dumps({"exp": int(time.time()) + _SESSION_TTL}).encode()
    sig = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(sig)}"


def valid_session(token: str) -> bool:
    if not token or "." not in token:
        return False
    try:
        p_b64, s_b64 = token.split(".", 1)
        payload = _b64d(p_b64)
        expected = hmac.new(_session_secret(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(s_b64), expected):
            return False
        return json.loads(payload).get("exp", 0) > time.time()
    except Exception:  # noqa: BLE001
        return False


def end_session(token: str) -> None:
    # Sesión sin estado: el logout borra la cookie en el cliente (no hay store que limpiar).
    return None
