"""Licencias offline firmadas (Ed25519).

La app SOLO lleva la clave pública → puede verificar licencias pero no falsificarlas.
El vendedor emite licencias firmando con la clave privada (ver `tools/make_license.py`).
No requiere servidor: la verificación es local. La licencia activada se guarda en
`secrets.json` (local al equipo).

Formato de licencia:  <base64url(payload_json)>.<base64url(firma)>
payload: {"name": ..., "email": ..., "exp": "YYYY-MM-DD" | null}
"""
from __future__ import annotations

import base64
import json
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import secrets_store

# Clave PÚBLICA de PressForge (generada una vez; la privada NO está en el repo).
_PUBLIC_KEY_B64 = "ALRPABD1Uqz7LRnSghe47gPVvfQz34h395laC6/F62A="


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify(license_key: str) -> dict | None:
    """Devuelve el payload si la licencia es válida (firma correcta y no expirada),
    o None si no lo es."""
    if not license_key or "." not in license_key:
        return None
    try:
        payload_b64, sig_b64 = license_key.strip().split(".", 1)
        payload = _b64url_decode(payload_b64)
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))
        pub.verify(_b64url_decode(sig_b64), payload)  # lanza si la firma no cuadra
        data = json.loads(payload)
        exp = data.get("exp")
        if exp and datetime.fromisoformat(exp) < datetime.now():
            return None  # expirada
        return data
    except Exception:  # noqa: BLE001 — cualquier fallo = licencia inválida
        return None


def is_licensed() -> bool:
    return verify(secrets_store.get_secret("license_key")) is not None


def license_info() -> dict:
    data = verify(secrets_store.get_secret("license_key"))
    if not data:
        return {"licensed": False}
    return {"licensed": True, "name": data.get("name", ""),
            "email": data.get("email", ""), "exp": data.get("exp")}


def activate(license_key: str) -> bool:
    if verify(license_key) is None:
        return False
    secrets_store.set_secret("license_key", license_key.strip())
    return True
