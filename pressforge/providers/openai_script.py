"""ScriptProvider basado en OpenAI con salida estructurada.

Genera en una sola llamada: idea viral + guion optimizado para retención +
storyboard (cada escena con su prompt de imagen). Mantener todo en una llamada
da coherencia visual y narrativa entre escenas.
"""
from __future__ import annotations

from ..config import get_settings
from ..models import Scene, Story, StoryDraft
from ._openai_client import client

_SYSTEM = """Eres un guionista experto en contenido viral histórico para reels \
verticales (TikTok/Reels/Shorts). Escribes en {language}.

Tu trabajo: a partir de un nicho, inventar UNA historia real e impactante y \
convertirla en un guion de documental corto (30-60s) optimizado para retención.

Reglas del guion:
- HOOK (escena 1): 0-3s, curiosidad extrema. Ej: "Este rey murió de una forma \
tan absurda que parece inventada."
- DESARROLLO: explicación rápida, lenguaje sencillo, sin relleno, ritmo alto.
- CIERRE (última escena): payoff sorprendente. Ej: "Y sí, esto quedó \
registrado en la historia."
- Total: 100-160 palabras repartidas entre las escenas.
- Prioriza rareza, shock, ironía y finales inesperados. Nada aburrido.
- Debe ser históricamente plausible/real, no inventado como falso.

Reglas de los image_prompt (en INGLÉS):
- Estilo "cinematic historical realism", iluminación dramática, 9:16 vertical.
- Coherencia visual entre escenas (misma época, paleta, calidad).
- Describe la escena concreta, sin texto ni letras en la imagen, sin marcas \
modernas si la época no corresponde."""

_REFINE_SYSTEM = """Eres un editor de guiones para reels históricos verticales \
(TikTok/Reels/Shorts). Escribes en {language}.

Recibes el guion que ESCRIBIÓ EL USUARIO. Tu trabajo es PULIRLO, no reescribir \
la historia:
- NO inventes hechos, fechas, nombres ni datos nuevos. Respeta el contenido del \
usuario. Si algo es ambiguo, mantenlo, no lo rellenes con invención.
- Mejora redacción, claridad y ritmo. Hazlo conciso, sin relleno.
- Convierte el inicio en un HOOK potente (0-3s) usando SOLO lo que el usuario \
aporta.
- Asegura un cierre con payoff.
- Divide el guion en escenas (la 1ª es el hook, la última el cierre).
- Crea un image_prompt en INGLÉS por escena: "cinematic historical realism", \
9:16 vertical, sin texto en la imagen, coherente entre escenas.
- Sugiere music_mood acorde al tono del guion del usuario."""


class OpenAIScriptProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate(self, niche: str, *, scenes: int, extra: str | None = None) -> Story:
        user = (
            f"Nicho: {niche}\n"
            f"Número de escenas: exactamente {scenes} "
            f"(la 1ª es el hook, la última el cierre).\n"
        )
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = client().beta.chat.completions.parse(
            model=self.settings.script_model,
            messages=[
                {"role": "system", "content": _SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.9,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")

        return self._to_story(draft, niche=niche)

    def refine(self, user_script: str, *, scenes: int, extra: str | None = None) -> Story:
        """Modo 'Mi guion': pule el texto del usuario sin inventar hechos."""
        user = (
            f"Guion del usuario:\n\"\"\"\n{user_script.strip()}\n\"\"\"\n\n"
            f"Optimízalo y divídelo en ~{scenes} escenas "
            f"(la 1ª es el hook, la última el cierre).\n"
        )
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = client().beta.chat.completions.parse(
            model=self.settings.script_model,
            messages=[
                {"role": "system", "content": _REFINE_SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.4,  # más fiel al original que en modo inventar
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")
        return self._to_story(draft, niche="Mi guion")

    @staticmethod
    def _to_story(draft: StoryDraft, *, niche: str) -> Story:
        return Story(
            niche=niche,
            title=draft.title,
            hook=draft.hook,
            cta=draft.cta,
            music_mood=draft.music_mood,
            scenes=[
                Scene(index=i, narration=s.narration, image_prompt=s.image_prompt)
                for i, s in enumerate(draft.scenes)
            ],
        )
