"""Contratos de los providers.

Son `Protocol`s (tipado estructural): cualquier clase que tenga los métodos
correctos sirve, no hace falta heredar. Esto mantiene cada paso intercambiable
—OpenAI hoy, modelo local mañana— sin acoplar el pipeline a una implementación.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import RenderJob, SourceFact, Story, Word


class ImageBlockedError(RuntimeError):
    """La generación de imagen fue rechazada por el filtro de seguridad."""


@runtime_checkable
class ScriptProvider(Protocol):
    def generate(self, niche: str, *, scenes: int, extra: str | None = None,
                 target_words: int | None = None, language: str | None = None) -> Story:
        """Idea + guion + storyboard a partir de un nicho (modo Inventar)."""
        ...

    def refine(self, user_script: str, *, scenes: int, extra: str | None = None,
               language: str | None = None) -> Story:
        """Pule el guion del usuario sin inventar (modo Mi guion)."""
        ...

    def from_source(self, fact: SourceFact, *, scenes: int, extra: str | None = None,
                    target_words: int | None = None, language: str | None = None) -> Story:
        """Guion fiel a hechos reales (modos Histórico / Qué pasó hoy / Reddit)."""
        ...

    def select_events(self, events: list[SourceFact], theme: str, count: int) -> list[int]:
        """Elige qué efemérides usar según el tema."""
        ...


@runtime_checkable
class ResearchProvider(Protocol):
    def search(self, topic: str, *, limit: int = 3) -> list[SourceFact]:
        """Hechos reales sobre un tema."""
        ...

    def on_this_day(self, month: int, day: int, *, limit: int = 30) -> list[SourceFact]:
        """Efemérides reales de una fecha."""
        ...


@runtime_checkable
class ImageProvider(Protocol):
    def generate(self, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        """Genera una imagen 9:16 para una escena y la guarda en out_path.

        Si `reference` es una imagen, recrea su composición en el estilo elegido."""
        ...


@runtime_checkable
class VoiceProvider(Protocol):
    def synthesize(self, text: str, out_path: Path) -> Path:
        """Narración por voz IA del guion completo."""
        ...


@runtime_checkable
class SubtitleProvider(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> list[Word]:
        """Alinea el audio narrado a palabras con timestamps.

        `language`: idioma del audio (ej. 'English'/'Spanish') para no transcribir
        un idioma como otro fonéticamente."""
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
