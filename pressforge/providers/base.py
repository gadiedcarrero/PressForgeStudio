"""Contratos de los providers.

Son `Protocol`s (tipado estructural): cualquier clase que tenga los métodos
correctos sirve, no hace falta heredar. Esto mantiene cada paso intercambiable
—OpenAI hoy, modelo local mañana— sin acoplar el pipeline a una implementación.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import RenderJob, Story, Word


@runtime_checkable
class ScriptProvider(Protocol):
    def generate(self, niche: str, *, scenes: int, extra: str | None = None) -> Story:
        """Idea + guion + storyboard a partir de un nicho."""
        ...


@runtime_checkable
class ImageProvider(Protocol):
    def generate(self, prompt: str, out_path: Path) -> Path:
        """Genera una imagen 9:16 para una escena y la guarda en out_path."""
        ...


@runtime_checkable
class VoiceProvider(Protocol):
    def synthesize(self, text: str, out_path: Path) -> Path:
        """Narración por voz IA del guion completo."""
        ...


@runtime_checkable
class SubtitleProvider(Protocol):
    def transcribe(self, audio_path: Path) -> list[Word]:
        """Alinea el audio narrado a palabras con timestamps."""
        ...


@runtime_checkable
class MusicProvider(Protocol):
    def get_track(self, *, mood: str | None = None, track: str | None = None) -> Path | None:
        """Devuelve la ruta a una pista de música de fondo (o None si no hay)."""
        ...


@runtime_checkable
class RenderProvider(Protocol):
    def render(self, job: RenderJob) -> Path:
        """Une imágenes + voz + subtítulos + música en el mp4 final."""
        ...
