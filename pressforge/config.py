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

    # --- ComfyUI (imágenes LOCALES gratis; IMAGE_PROVIDER=local) ---
    # Requiere un servidor ComfyUI corriendo (ver docs). InstantID mantiene la
    # misma cara del personaje entre escenas cuando hay imagen de referencia.
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_checkpoint: str = "RealVisXL_V5.0_fp16.safetensors"
    # Lightning LoRA: acelera ~3-4× (8 pasos en vez de 30). Déjalo vacío para
    # calidad máxima a 30 pasos (más lento). Con LoRA, steps/cfg bajan solos.
    comfyui_lightning_lora: str = "sdxl_lightning_8step_lora.safetensors"
    comfyui_steps: int = 8       # con Lightning: 8 · sin Lightning sube a ~28
    comfyui_cfg: float = 2.0     # con Lightning: ~2 · sin Lightning ~5
    # InstantID: peso ↑ fija más la cara (close-up); ↓ deja respirar el encuadre.
    # end_at: deja de aplicar la cara antes del final → planos más abiertos/variados.
    instantid_weight: float = 0.65
    instantid_end_at: float = 0.7

    # --- Video LOCAL (animación gratis con LTX-Video en ComfyUI) ---
    comfyui_video_model: str = "ltxv-2b-0.9.8-distilled.safetensors"
    comfyui_video_t5: str = "t5xxl_fp16.safetensors"
    comfyui_video_steps: int = 8     # distilled: 8 pasos (rápido)
    comfyui_video_cfg: float = 1.0   # distilled: sin CFG

    # --- Subtítulos locales (faster-whisper, GRATIS; SUBTITLE_PROVIDER=whisper-local) ---
    local_whisper_model: str = "base"  # base/small/medium · base = rápido y suficiente

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


def branding_path() -> Path:
    """Brand kits (logos + banners por marca). En `<STORAGE_DIR>/branding` si hay
    STORAGE_DIR (compartido entre PCs vía Drive); si no, `assets/branding`."""
    s = get_settings()
    if s.storage_dir:
        return Path(s.storage_dir).expanduser() / "branding"
    return Path("assets/branding")
