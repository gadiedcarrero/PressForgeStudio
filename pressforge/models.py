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
    hook: str = Field(
        description="Pattern interrupt de 0-3s que abre un bucle de curiosidad. "
        "Empieza por lo más impactante/contradictorio, NUNCA por contexto o "
        "fecha. Debe coincidir con la narración de la escena 1."
    )
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
        "cierre. Cada escena es UNA idea corta (~10-14 palabras, idealmente una "
        "frase) para que la imagen cambie cada 3-5 s. Usa tantas escenas como "
        "pida la narración (más texto → más escenas). La concatenación de las "
        "narraciones forma el guion completo."
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
class SourceFact:
    """Un hecho real recuperado de una fuente (Wikipedia)."""

    title: str
    extract: str
    url: str
    year: int | None = None


@dataclass
class Story:
    niche: str
    title: str
    hook: str
    cta: str
    scenes: list[Scene]
    music_mood: str = ""
    source_title: str = ""
    source_url: str = ""

    @property
    def full_narration(self) -> str:
        """Guion completo que se manda a TTS."""
        return " ".join(s.narration.strip() for s in self.scenes)


def story_to_dict(story: "Story") -> dict:
    """Serializa el guion para enviarlo a la UI (editable antes de producir)."""
    return {
        "niche": story.niche,
        "title": story.title,
        "hook": story.hook,
        "cta": story.cta,
        "music_mood": story.music_mood,
        "source_title": story.source_title,
        "source_url": story.source_url,
        "scenes": [
            {"index": s.index, "narration": s.narration, "image_prompt": s.image_prompt}
            for s in story.scenes
        ],
    }


def story_from_dict(d: dict) -> "Story":
    """Reconstruye un Story desde el dict (posiblemente editado) de la UI."""
    scenes = [
        Scene(index=i, narration=s.get("narration", ""), image_prompt=s.get("image_prompt", ""))
        for i, s in enumerate(d.get("scenes", []))
    ]
    return Story(
        niche=d.get("niche", ""),
        title=d.get("title", ""),
        hook=d.get("hook", ""),
        cta=d.get("cta", ""),
        music_mood=d.get("music_mood", ""),
        source_title=d.get("source_title", ""),
        source_url=d.get("source_url", ""),
        scenes=scenes,
    )


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
