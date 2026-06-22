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
        description="IDENTIDAD FIJA del personaje (lo que NUNCA cambia entre "
        "escenas), EN INGLÉS, para repetir en cada imagen y mantener la MISMA "
        "CARA: rostro y rasgos faciales, forma/color de ojos, etnia/tono de piel, "
        "color y estilo de pelo, edad aproximada, género. "
        "NO incluyas la ropa NI la complexión/cuerpo: eso PUEDE CAMBIAR escena a "
        "escena (un personaje puede adelgazar, engordar, musculares, cambiarse de "
        "ropa) y se describe en el image_prompt de cada escena. "
        "Ej: 'a woman in her late 20s, Latina, oval face, warm brown eyes, long "
        "dark wavy hair, light olive skin'. Sin texto ni nombres en la imagen."
    )
    voice_style: str = Field(
        default="",
        description="Descripción FIJA y distintiva de la VOZ del personaje, EN "
        "INGLÉS, para mantenerla IGUAL en todos los clips (edad, género, tono, "
        "timbre). Ej: 'a warm deep adult male voice, calm and friendly' o 'a "
        "bright cheerful young female voice'. Cada personaje con una voz distinta."
    )


class SceneDraft(BaseModel):
    narration: str = Field(
        description="Fragmento narrado de esta escena. Es un SEGMENTO de una "
        "narración continua: al unir los fragmentos de todas las escenas EN "
        "ORDEN debe leerse como un texto fluido y natural (no frases sueltas y "
        "robóticas). Usa conectores/transiciones; una frase puede continuar de "
        "una escena a la siguiente. Es lo que la voz IA leerá de corrido."
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
    speaker: str = Field(
        default="",
        description="En modo DIÁLOGO: nombre EXACTO (de `characters`) del "
        "personaje que dice la línea de esta escena (el que hablará con su voz y "
        "hará lip-sync). Vacío si no hay diálogo (narración normal).",
    )


class DialogueBeat(BaseModel):
    speaker: str = Field(
        description="Nombre EXACTO (de `characters`) del personaje que dice esta "
        "línea. Déjalo VACÍO solo si es una acción sin diálogo (un plano sin que "
        "nadie hable)."
    )
    line: str = Field(
        description="Las palabras EXACTAS que dice el personaje, VERBATIM del "
        "guion. NO las parafrasees, NO las describas en tercera persona, NO "
        "narres la acción. Solo lo que sale por su boca. VACÍO si es acción sin "
        "diálogo."
    )
    image_prompt: str = Field(
        description="EN INGLÉS. La escena COMPLETA que se VE en este momento: "
        "plano amplio / cuerpo entero mostrando el escenario, el personaje que "
        "habla hablando con su emoción, y el otro reaccionando de forma coherente. "
        "Incluye SIEMPRE el VESTUARIO ACTUAL COMPLETO de cada personaje visible, "
        "arrastrando cualquier cambio ya ocurrido (si Víctor YA se cambió a "
        "pantalón negro, en esta y TODAS las siguientes lleva pantalón negro). "
        "Mantén la misma etnia/cara. Sin texto en la imagen."
    )


class DialogueDraft(BaseModel):
    title: str = Field(description="Título interno corto de la escena/diálogo.")
    music_mood: str = Field(
        description="2-5 etiquetas en inglés del tono musical (ver vocabulario "
        "habitual). Ej: 'romantic uplifting' o 'fun light'."
    )
    characters: list[CharacterDraft] = Field(
        description="Los personajes que hablan o aparecen, con su IDENTIDAD FIJA "
        "(cara, etnia, ojos, pelo, edad; SIN ropa ni cuerpo, que cambian)."
    )
    beats: list[DialogueBeat] = Field(
        description="La secuencia EN ORDEN del guion. Una entrada por cada línea "
        "de diálogo (y, si hace falta, beats de acción sin diálogo). NO inventes "
        "líneas; usa las del guion."
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
        "cierre. Cada escena es un CORTE VISUAL (~10-14 palabras) para que la "
        "imagen cambie cada 3-5 s, PERO sus narraciones, leídas en orden, deben "
        "formar UNA narración continua y fluida (no una lista de frases cortas "
        "inconexas). Usa tantas escenas como pida la narración (más texto → más "
        "escenas)."
    )


# ─── Objetos del pipeline ─────────────────────────────────────────────────────
@dataclass
class Character:
    """Personaje con apariencia visual fija (para que salga igual en cada imagen)."""

    name: str
    description: str
    voice: str = ""  # voz (id ElevenLabs / nombre OpenAI) para sus líneas en modo diálogo
    voice_style: str = ""  # descripción de voz fija (para Veo 3, consistencia entre clips)
    reference: str = ""  # ruta a imagen de referencia (Seedance reference-to-video)


@dataclass
class Scene:
    index: int
    narration: str
    image_prompt: str
    characters: list[str] = field(default_factory=list)  # nombres que aparecen aquí
    speaker: str = ""  # en modo diálogo: quién dice la línea (lip-sync + su voz)
    reference: str = ""  # archivo de imagen de referencia (opcional) para recrear la escena
    image_path: Path | None = None
    clip_path: Path | None = None  # video animado de la escena (modo Video animado completo)
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
    language: str = "Spanish"  # idioma de salida del guion/voz (ej. "Spanish", "English")
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
        "language": story.language,
        "characters": [{"name": c.name, "description": c.description, "voice": c.voice,
                        "voice_style": c.voice_style, "reference": c.reference} for c in story.characters],
        "source_title": story.source_title,
        "source_url": story.source_url,
        "source_date": story.source_date,
        "scenes": [
            {"index": s.index, "narration": s.narration, "image_prompt": s.image_prompt,
             "characters": list(s.characters), "speaker": s.speaker, "reference": s.reference}
            for s in story.scenes
        ],
    }


def story_from_dict(d: dict) -> "Story":
    """Reconstruye un Story desde el dict (posiblemente editado) de la UI."""
    scenes = [
        Scene(index=i, narration=s.get("narration", ""), image_prompt=s.get("image_prompt", ""),
              characters=list(s.get("characters") or []), speaker=s.get("speaker", "") or "",
              reference=s.get("reference", "") or "")
        for i, s in enumerate(d.get("scenes", []))
    ]
    characters = [
        Character(name=c.get("name", ""), description=c.get("description", ""),
                  voice=c.get("voice", "") or "", voice_style=c.get("voice_style", "") or "",
                  reference=c.get("reference", "") or "")
        for c in (d.get("characters") or []) if c.get("name")
    ]
    return Story(
        niche=d.get("niche", ""),
        title=d.get("title", ""),
        hook=d.get("hook", ""),
        cta=d.get("cta", ""),
        music_mood=d.get("music_mood", ""),
        language=d.get("language", "Spanish") or "Spanish",
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
