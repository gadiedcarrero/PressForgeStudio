"""Cliente OpenAI compartido por los providers que lo usan."""
from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from ..config import get_settings


@lru_cache
def client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "Falta OPENAI_API_KEY. Cópiala en tu archivo .env "
            "(ver .env.example)."
        )
    return OpenAI(api_key=settings.openai_api_key)
