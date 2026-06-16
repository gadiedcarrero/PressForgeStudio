"""Modelos de datos que fluyen por el pipeline.

`*Draft` = lo que el LLM devuelve (structured output). El resto son los objetos
ya enriquecidos que pasan de un paso al siguiente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field


# ─── Salida estructurada del ScriptProvider ──────────────────────────────────
class CharacterDraft(BaseModel):
    name: str = Field(
        description="Nombre del personaje tal como aparece en la historia "
        "(ej. 'Marcy Borders'). Para anónimos, una etiqueta corta y estable "
        "(ej. 'el soldado', 'la niña')."
    )
    description: str = Field(
        description="Descripción VISUAL fija y detallada del personaje, EN INGLÉS, "
        "para repetir en cada imagen donde aparezca y mantenerlo idéntico: edad "
        "aproximada, género, etnia/tono de piel, color y estilo de pelo, "
        "complexión, ropa característica de la época y rasgos distintivos. "
        "Ej: 'a woman in her late 20s, light brown shoulder-length hair, fair "
        "skin, wearing a dark business suit'. Sin texto ni nombres en la imagen."
    )


class SceneDraft(BaseModel):
    narration: str = Field(
        description="Texto narrado de esta escena. Frases cortas, lenguaje "
        "sencillo, sin relleno. Es lo que la voz IA leerá."
    )
    image_prompt: str = Field(
        description="Prompt visual en inglés para generar la imagen de la "
        "escena. Estilo 'cinematic historical realism', vertical 9:16, "
        "coherente con el resto del reel. Sin texto en la imagen. Debe describir "
        "CONCRETAMENTE el sujeto/acción real de la narración (NO algo vago o "
        "simbólico desconectado del tema)."
    )
    characters: list[str] = Field(
        default_factory=list,
        description="Nombres (de la lista `characters`) de los personajes que "
        "APARECEN en esta escena. Vacío si la escena no muestra a ningún "
        "personaje concreto. Los nombres deben coincidir exactamente.",
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
    characters: list[CharacterDraft] = Field(
        default_factory=list,
        description="Personajes recurrentes de la historia (personas con "
        "apariencia concreta) con su descripción visual fija. Detéctalos leyendo "
        "TODA la historia. Si la historia no tiene personas concretas (solo "
        "lugares/objetos/conceptos), deja la lista vacía.",
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
class Character:
    """Personaje con apariencia visual fija (para que salga igual en cada imagen)."""

    name: str
    description: str


@dataclass
class Scene:
    index: int
    narration: str
    image_prompt: str
    characters: list[str] = field(default_factory=list)  # nombres que aparecen aquí
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
    characters: list[Character] = field(default_factory=list)
    source_title: str = ""
    source_url: str = ""
    source_date: str = ""  # fecha legible del hecho (ej. "14 de junio de 1945")

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
        "characters": [{"name": c.name, "description": c.description} for c in story.characters],
        "source_title": story.source_title,
        "source_url": story.source_url,
        "source_date": story.source_date,
        "scenes": [
            {"index": s.index, "narration": s.narration, "image_prompt": s.image_prompt,
             "characters": list(s.characters)}
            for s in story.scenes
        ],
    }


def story_from_dict(d: dict) -> "Story":
    """Reconstruye un Story desde el dict (posiblemente editado) de la UI."""
    scenes = [
        Scene(index=i, narration=s.get("narration", ""), image_prompt=s.get("image_prompt", ""),
              characters=list(s.get("characters") or []))
        for i, s in enumerate(d.get("scenes", []))
    ]
    characters = [
        Character(name=c.get("name", ""), description=c.get("description", ""))
        for c in (d.get("characters") or []) if c.get("name")
    ]
    return Story(
        niche=d.get("niche", ""),
        title=d.get("title", ""),
        hook=d.get("hook", ""),
        cta=d.get("cta", ""),
        music_mood=d.get("music_mood", ""),
        characters=characters,
        source_title=d.get("source_title", ""),
        source_url=d.get("source_url", ""),
        source_date=d.get("source_date", ""),
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
