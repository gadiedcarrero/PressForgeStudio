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
