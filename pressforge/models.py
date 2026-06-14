"""Modelos de datos que fluyen por el pipeline.

`*Draft` = lo que el LLM devuelve (structured output). El resto son los objetos
ya enriquecidos que pasan de un paso al siguiente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field


# ─── Salida estructurada del ScriptProvider ──────────────────────────────────
class SceneDraft(BaseModel):
    narration: str = Field(
        description="Texto narrado de esta escena. Frases cortas, lenguaje "
        "sencillo, sin relleno. Es lo que la voz IA leerá."
    )
    image_prompt: str = Field(
        description="Prompt visual en inglés para generar la imagen de la "
        "escena. Estilo 'cinematic historical realism', vertical 9:16, "
        "coherente con el resto del reel. Sin texto en la imagen."
    )


class StoryDraft(BaseModel):
    title: str = Field(description="Título interno de la historia.")
    hook: str = Field(description="Gancho de 0-3s que crea curiosidad extrema.")
    cta: str = Field(description="Cierre sorprendente con payoff.")
    music_mood: str = Field(
        description="2-5 etiquetas en inglés, separadas por espacios, que "
        "describen el tono musical ideal para esta historia. Elige de un "
        "vocabulario consistente: epic, war, battle, mystery, suspense, tense, "
        "tragic, sad, dark, horror, ancient, medieval, wonder, curious, "
        "triumphant, dramatic. Ej: 'tragic dramatic' o 'mystery ancient'."
    )
    scenes: list[SceneDraft] = Field(
        description="Escenas en orden. La primera ES el hook; la última ES el "
        "cierre. La concatenación de las narraciones forma el guion completo "
        "(100-160 palabras en total)."
    )


# ─── Objetos del pipeline ─────────────────────────────────────────────────────
@dataclass
class Scene:
    index: int
    narration: str
    image_prompt: str
    image_path: Path | None = None
    duration: float = 0.0  # segundos, asignado tras conocer la duración del audio


@dataclass
class Story:
    niche: str
    title: str
    hook: str
    cta: str
    scenes: list[Scene]
    music_mood: str = ""

    @property
    def full_narration(self) -> str:
        """Guion completo que se manda a TTS."""
        return " ".join(s.narration.strip() for s in self.scenes)


@dataclass
class Word:
    """Palabra con timestamps (del SubtitleProvider)."""

    text: str
    start: float
    end: float


@dataclass
class RenderJob:
    """Todo lo que el RenderProvider necesita para producir el mp4."""

    workdir: Path
    scenes: list[Scene]
    audio_path: Path
    subtitles_path: Path
    output_path: Path
    music_path: Path | None = None
    width: int = 1080
    height: int = 1920
    fps: int = 30
    music_volume: float = 0.12


@dataclass
class ReelResult:
    story: Story
    video_path: Path
    workdir: Path
    duration: float
    extras: dict = field(default_factory=dict)
