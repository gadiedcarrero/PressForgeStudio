"""Configuración global cargada desde el entorno / archivo .env.

Una sola fuente de verdad. Cada provider lee de aquí lo que necesita, así que
cambiar de modelo o de provider es editar `.env`, no el código.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Credenciales ---
    openai_api_key: str = ""

    # --- Selección de providers ---
    script_provider: str = "openai"
    image_provider: str = "openai"
    voice_provider: str = "openai"
    subtitle_provider: str = "whisper"
    render_provider: str = "ffmpeg"
    music_provider: str = "local"
    research_provider: str = "wikipedia"

    # --- Modelos ---
    script_model: str = "gpt-4o"
    image_model: str = "gpt-image-1"
    voice_model: str = "gpt-4o-mini-tts"
    subtitle_model: str = "whisper-1"

    # --- Voz ---
    voice_name: str = "onyx"
    voice_instructions: str = (
        "Narrador de documental histórico. Tono dramático, intrigante y "
        "cinematográfico. Ritmo ágil. Español neutro."
    )

    # --- Contenido ---
    language: str = "es"

    # --- Render ---
    fps: int = 30
    video_width: int = 1080
    video_height: int = 1920
    image_quality: str = "medium"
    music_volume: float = 0.12


@lru_cache
def get_settings() -> Settings:
    return Settings()
