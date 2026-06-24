"""Modo Director — prompts cinematográficos ultra-detallados (estilo Dreamina-Octo).

La "magia" de Dreamina no es solo el modelo (Seedance, que ya usamos): es CÓMO se
le habla. Define las ENTIDADES (personajes y props) una vez con una descripción
visual fija y reutilizable, y describe cada TOMA con dirección cinematográfica
completa (encuadre, lente, movimiento, bloqueo, continuidad). Aquí generamos ese
guion estructurado con la IA y lo ensamblamos en un prompt rico por toma, listo
para cualquier motor de video (Seedance/fal o local).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DirectorEntity(BaseModel):
    """Una entidad reutilizable (personaje, prop o escenario) con apariencia fija."""

    name: str = Field(description="Nombre corto de referencia, p. ej. 'Butcher', "
                      "'Baby Dragon', 'Cleaver'. Único y estable.")
    kind: str = Field(description="Tipo: 'character' (persona/criatura), 'prop' "
                      "(objeto), o 'setting' (escenario/lugar).")
    description: str = Field(description="EN INGLÉS. Descripción visual FIJA, "
                             "hiper-detallada y reutilizable que NUNCA cambia entre "
                             "tomas (para consistencia): forma, materiales, colores, "
                             "marcas, textura, rasgos. Para personajes: cara, etnia, "
                             "ojos, pelo, edad (SIN ropa, que puede cambiar).")
    voice_style: str = Field(default="", description="Solo personajes que hablan. EN "
                             "INGLÉS: edad/género/tono/timbre fijos para mantener la "
                             "MISMA voz en todas las tomas. Ej: 'cold aristocratic "
                             "clipped British female voice'.")


class DirectorShot(BaseModel):
    """Una toma con dirección cinematográfica completa."""

    action: str = Field(description="EN INGLÉS. Qué se VE y ocurre en la toma, "
                        "concreto y detallado: sujeto, acción, ambiente, luz, "
                        "atmósfera. Referencia las entidades por su nombre.")
    camera: str = Field(description="EN INGLÉS. Dirección de cámara: encuadre (wide/"
                        "medium/close), lente (ej. 35mm/50mm/85mm), altura y ángulo, "
                        "movimiento (dolly in, slow push, static, tracking), bloqueo.")
    entities: list[str] = Field(default_factory=list, description="Nombres (de la "
                                "lista `entities`) que APARECEN en esta toma.")
    speaker: str = Field(default="", description="En diálogo: nombre EXACTO del "
                         "personaje que habla en esta toma (lip-sync + su voz). Vacío "
                         "si es una toma sin diálogo.")
    line: str = Field(default="", description="Diálogo: las palabras EXACTAS que dice "
                      "el `speaker`, verbatim. Vacío si no hay diálogo.")
    continuity: str = Field(default="", description="EN INGLÉS, opcional: notas de "
                            "continuidad para esta toma (dirección de pantalla, qué se "
                            "mantiene del plano anterior, revelaciones). Ej: 'keep "
                            "screen direction, ship enters from left as before'.")


class DirectorScript(BaseModel):
    """Guion de Director completo: estilo global + entidades + tomas."""

    title: str = Field(description="Título interno corto.")
    look: str = Field(description="EN INGLÉS. Estética global que se repite en TODAS "
                      "las tomas: film stock/grano, paleta de color, contraste, mood, "
                      "calidad. Ej: 'anamorphic cinematic, teal-orange palette, fine "
                      "film grain, dramatic chiaroscuro, no lens flare'.")
    aspect_ratio: str = Field(default="9:16 vertical", description="Relación de "
                              "aspecto, ej. '9:16 vertical' o '2.39:1 anamorphic'.")
    music_mood: str = Field(default="", description="2-5 etiquetas EN INGLÉS del tono "
                            "musical. Ej: 'tense dramatic dark'.")
    entities: list[DirectorEntity] = Field(description="Todas las entidades "
                                           "(personajes, props, escenarios) con su "
                                           "apariencia fija reutilizable.")
    shots: list[DirectorShot] = Field(description="Las tomas EN ORDEN. Cada una es un "
                                      "corte con dirección completa.")


# ─── Ensamblado del prompt por toma (lo que recibe el motor de video) ───
def _kind_tag(kind: str) -> str:
    """Normaliza el tipo (el LLM puede decir person/creature/object/place…)."""
    k = (kind or "").strip().lower()
    if k in ("prop", "object", "item", "weapon", "tool"):
        return "PROP"
    if k in ("setting", "place", "location", "scenery", "environment"):
        return "SETTING"
    return "CHARACTER"  # person, creature, character, animal…


def _entity_lines(script: DirectorScript, names: list[str]) -> str:
    """Descripciones fijas de las entidades presentes (consistencia en cada toma)."""
    by_name = {e.name.strip().lower(): e for e in script.entities}
    out = []
    for n in names:
        e = by_name.get((n or "").strip().lower())
        if e and e.description.strip():
            out.append(f"  - {e.name} [{_kind_tag(e.kind)}]: {e.description.strip()}")
    return "\n".join(out)


def build_shot_prompt(script: DirectorScript, shot: DirectorShot, *,
                      with_dialogue: bool = True) -> str:
    """Ensambla la toma en un prompt rico estilo Dreamina (entidades + dirección).

    `with_dialogue=False` → no inyecta la línea hablada en el prompt (modo
    audio-first: la voz se pone aparte con ElevenLabs y el video va mudo)."""
    ents = _entity_lines(script, shot.entities or [s.name for s in script.entities])
    parts = [
        f"[STYLE] {script.look.strip()}. {script.aspect_ratio.strip()}. "
        f"Consistent screen direction — geography never flips.",
    ]
    if ents:
        parts.append("[ENTITIES — keep EXACTLY consistent across shots]\n" + ents)
    parts.append(f"[SHOT] {shot.action.strip()}")
    if shot.camera.strip():
        parts.append(f"[CAMERA] {shot.camera.strip()}")
    if shot.continuity.strip():
        parts.append(f"[CONTINUITY] {shot.continuity.strip()}")
    if with_dialogue and shot.speaker.strip() and shot.line.strip():
        spk = next((e for e in script.entities
                    if e.name.strip().lower() == shot.speaker.strip().lower()), None)
        voice = f" (voice: {spk.voice_style.strip()})" if spk and spk.voice_style.strip() else ""
        parts.append(f'[DIALOGUE] {shot.speaker} says, lip-synced: "{shot.line.strip()}"{voice}')
    parts.append("No on-screen text, no watermark, no captions.")
    return "\n".join(parts)


def director_to_story(script: DirectorScript, *, language: str | None = None):
    """Convierte un DirectorScript en un Story para reusar el pipeline existente.

    Cada toma → escena: `narration` = la línea hablada (diálogo) y `image_prompt` =
    el prompt rico ensamblado (entidades + cámara + continuidad). Las entidades de
    tipo personaje → characters con su voice_style fijo."""
    from .models import Character, Scene, Story

    chars = [Character(name=e.name.strip(), description=e.description.strip(),
                       voice_style=(e.voice_style or "").strip())
             for e in script.entities
             if _kind_tag(e.kind) == "CHARACTER" and e.name.strip() and e.description.strip()]
    names = {c.name for c in chars}
    has_dialogue = any(s.speaker.strip() and s.line.strip() for s in script.shots)
    scenes = []
    for i, sh in enumerate(script.shots):
        spk = sh.speaker.strip() if sh.speaker.strip() in names else ""
        scenes.append(Scene(
            index=i,
            narration=(sh.line.strip() if (spk and sh.line.strip()) else ""),
            image_prompt=build_shot_prompt(script, sh, with_dialogue=has_dialogue),
            characters=[n for n in (sh.entities or []) if n in names],
            speaker=spk,
        ))
    return Story(
        niche="Director", title=script.title or "Director",
        hook=scenes[0].narration if scenes else "",
        cta=scenes[-1].narration if scenes else "",
        music_mood=script.music_mood or "", characters=chars, scenes=scenes,
        language=language or "Spanish",
    )
