"""Cliente OpenAI compartido por los providers que lo usan.

La API key se resuelve en este orden (modelo BYOK):
  1. Lo que el usuario guardó en la UI (Ajustes → API Keys) → secrets.json
  2. Como respaldo, `OPENAI_API_KEY` del .env (desarrollo)

No se cachea el cliente para que un cambio de key en la UI tenga efecto al
instante (construir el cliente es barato, sin red).
"""
from __future__ import annotations

from openai import OpenAI

from ..config import get_settings
from ..secrets_store import get_secret


def resolve_openai_key() -> str:
    return get_secret("openai_api_key") or get_settings().openai_api_key


def client() -> OpenAI:
    key = resolve_openai_key()
    if not key:
        raise RuntimeError(
            "Falta la API key de OpenAI. Añádela en Ajustes → API Keys."
        )
    return OpenAI(api_key=key)
