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
_IMAGE = {"openai": OpenAIImageProvider}
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


def get_image_provider() -> ImageProvider:
    return _pick(_IMAGE, get_settings().image_provider, "Image")


def get_voice_provider() -> VoiceProvider:
    return _pick(_VOICE, get_settings().voice_provider, "Voice")


def get_subtitle_provider() -> SubtitleProvider:
    return _pick(_SUBTITLE, get_settings().subtitle_provider, "Subtitle")


def get_render_provider() -> RenderProvider:
    return _pick(_RENDER, get_settings().render_provider, "Render")


def get_music_provider() -> MusicProvider:
    return _pick(_MUSIC, get_settings().music_provider, "Music")


def get_research_provider() -> ResearchProvider:
    return _pick(_RESEARCH, get_settings().research_provider, "Research")
