"""Almacén local de API keys (modelo BYOK: cada cliente pone las suyas).

Se guardan en `secrets.json` en la carpeta del proyecto, **local a cada equipo**
y fuera de git y de la sincronización de Drive (a diferencia de `data/`). Así
las claves nunca viajan a la nube ni al repo.

El usuario las introduce en la UI (Ajustes → API Keys); como respaldo, si una
clave no está aquí, se usa la del `.env` (útil en desarrollo).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_FILE = Path("secrets.json")  # local al equipo (gitignored, NO en STORAGE_DIR)
_lock = threading.RLock()

# Claves conocidas: nombre interno -> etiqueta para la UI.
KNOWN = {
    "openai_api_key": "OpenAI API Key",
    "elevenlabs_api_key": "ElevenLabs API Key (voz, opcional)",
    "fal_api_key": "fal.ai API Key (video animado, opcional)",
}


def _load() -> dict:
    if _FILE.exists():
        try:
            return json.loads(_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(data: dict) -> None:
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_secret(name: str) -> str:
    with _lock:
        return (_load().get(name) or "").strip()


def set_secret(name: str, value: str) -> None:
    with _lock:
        data = _load()
        data[name] = value.strip()
        _save(data)


def _mask(value: str) -> str:
    if not value:
        return ""
    return (value[:6] + "…" + value[-4:]) if len(value) > 12 else "••••"


def status() -> dict:
    """Estado de cada clave conocida para la UI (sin exponer el valor completo)."""
    with _lock:
        data = _load()
    out = {}
    for name, label in KNOWN.items():
        val = (data.get(name) or "").strip()
        out[name] = {"label": label, "set": bool(val), "masked": _mask(val)}
    return out
