"""Fábrica de providers.

Lee la config y devuelve la implementación elegida para cada paso. Para añadir
un provider nuevo (ElevenLabs, Replicate, modelo local…) basta con registrarlo
en el diccionario correspondiente; el pipeline no cambia.
"""
from __future__ import annotations

from .config import get_settings
from .providers.base import (
    ImageProvider,
    MusicProvider,
    RenderProvider,
    ResearchProvider,
    ScriptProvider,
    SubtitleProvider,
    VoiceProvider,
)
from .providers.comfyui_image import ComfyUIImageProvider
from .providers.elevenlabs_voice import ElevenLabsVoiceProvider
from .providers.ffmpeg_render import FFmpegRenderProvider
from .providers.local_music import LocalLibraryMusicProvider
from .providers.openai_image import OpenAIImageProvider
from .providers.ollama_script import OllamaScriptProvider
from .providers.openai_script import OpenAIScriptProvider
from .providers.openai_voice import OpenAIVoiceProvider
from .providers.whisper_subtitle import WhisperSubtitleProvider
from .providers.wikipedia_research import WikipediaResearch

_SCRIPT = {"openai": OpenAIScriptProvider, "ollama": OllamaScriptProvider}
_IMAGE = {"openai": OpenAIImageProvider, "local": ComfyUIImageProvider, "comfyui": ComfyUIImageProvider}
_VOICE = {"openai": OpenAIVoiceProvider, "elevenlabs": ElevenLabsVoiceProvider}
_SUBTITLE = {"whisper": WhisperSubtitleProvider}
_RENDER = {"ffmpeg": FFmpegRenderProvider}
_MUSIC = {"local": LocalLibraryMusicProvider}
_RESEARCH = {"wikipedia": WikipediaResearch}


def _pick(table: dict, key: str, kind: str):
    try:
        return table[key]()
    except KeyError:
        opciones = ", ".join(table)
        raise ValueError(
            f"{kind} provider desconocido: '{key}'. Disponibles: {opciones}."
        )


def get_script_provider() -> ScriptProvider:
    return _pick(_SCRIPT, get_settings().script_provider, "Script")


def get_image_provider(override: str | None = None) -> ImageProvider:
    # override: elige el provider por reel (UI) sin tocar el .env ni reiniciar.
    return _pick(_IMAGE, (override or "").strip() or get_settings().image_provider, "Image")


def get_voice_provider() -> VoiceProvider:
    # Preferencia elegida en la UI (Ajustes → Voz) por encima del .env.
    from .secrets_store import get_secret

    name = get_secret("voice_provider") or get_settings().voice_provider
    return _pick(_VOICE, name, "Voice")


def get_subtitle_provider() -> SubtitleProvider:
    return _pick(_SUBTITLE, get_settings().subtitle_provider, "Subtitle")


def get_render_provider() -> RenderProvider:
    return _pick(_RENDER, get_settings().render_provider, "Render")


def get_music_provider() -> MusicProvider:
    return _pick(_MUSIC, get_settings().music_provider, "Music")


def get_research_provider() -> ResearchProvider:
    return _pick(_RESEARCH, get_settings().research_provider, "Research")
