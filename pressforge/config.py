"""Configuración global cargada desde el entorno / archivo .env.

Una sola fuente de verdad. Cada provider lee de aquí lo que necesita, así que
cambiar de modelo o de provider es editar `.env`, no el código.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    # --- Ollama (guion local gratis; SCRIPT_PROVIDER=ollama) ---
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3:30b"

    # --- ElevenLabs (voz premium; VOICE_PROVIDER=elevenlabs) ---
    elevenlabs_api_key: str = ""  # respaldo .env; preferido: Ajustes → API Keys
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"  # voz por defecto (cámbiala por una en español)
    elevenlabs_model: str = "eleven_multilingual_v2"

    # --- Voz ---
    voice_name: str = "onyx"
    voice_instructions: str = (
        "Narrador de documental histórico. Tono dramático, intrigante y "
        "cinematográfico. Ritmo ágil. Español neutro."
    )

    # --- Contenido ---
    language: str = "es"

    # --- Almacenamiento (sincronizable entre PCs) ---
    # storage_dir: carpeta base donde viven los datos (marcas, cola) y los reels
    # generados. Déjala vacía para usar la carpeta del proyecto (comportamiento
    # de siempre). Apúntala a tu carpeta de Google Drive / Dropbox —la MISMA ruta
    # sincronizada en cada PC— para acceder a todo el contenido desde cualquier
    # equipo. data_dir/output_dir permiten afinar cada una por separado.
    storage_dir: str = ""
    data_dir: str = ""
    output_dir: str = ""
    music_dir: str = ""

    # --- Render ---
    fps: int = 30
    video_width: int = 1080
    video_height: int = 1920
    image_quality: str = "medium"
    music_volume: float = 0.12


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _resolve(base: str, explicit: str, default_name: str) -> Path:
    """Resuelve una carpeta de almacenamiento.

    Prioridad: override explícito > carpeta base (storage_dir) > carpeta del
    proyecto (./<default_name>). Soporta `~` y rutas con espacios (típico en
    Google Drive / Dropbox tanto en Mac como en Windows).
    """
    if explicit:
        return Path(explicit).expanduser()
    if base:
        return Path(base).expanduser() / default_name
    return Path(default_name)


def data_path() -> Path:
    """Carpeta de datos locales (marcas, cola, canales → publish.json)."""
    s = get_settings()
    return _resolve(s.storage_dir, s.data_dir, "data")


def output_path() -> Path:
    """Carpeta raíz de los reels generados (output/<fecha>-<slug>/)."""
    s = get_settings()
    return _resolve(s.storage_dir, s.output_dir, "output")


def music_path() -> Path:
    """Biblioteca de música. Por defecto `assets/music` (incluida en el repo);
    si hay STORAGE_DIR, va a `<STORAGE_DIR>/music` para compartirla entre PCs."""
    s = get_settings()
    if s.music_dir:
        return Path(s.music_dir).expanduser()
    if s.storage_dir:
        return Path(s.storage_dir).expanduser() / "music"
    return Path("assets/music")
