"""ImageProvider con gpt-image-1.

gpt-image-1 entrega el tamaño retrato más cercano a 9:16 (1024x1536). El render
se encarga después de escalar/recortar a 1080x1920 con el efecto Ken Burns.

Robustez ante el filtro de seguridad: algunos temas históricos (mitología,
guerras…) disparan la moderación de OpenAI. Si pasa, reintentamos con un prompt
suavizado; si aún así se bloquea, lanzamos `ImageBlockedError` para que el
pipeline use una alternativa en vez de tumbar todo el reel.
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..config import get_settings
from .base import ImageBlockedError
from ._openai_client import client

# Sufijo añadido a cada prompt: formato + estilo + barandillas de seguridad.
_STYLE_SUFFIX = (
    ", cinematic historical realism, dramatic lighting, highly detailed, "
    "vertical 9:16 composition, no text, no watermark, no modern objects, "
    "tasteful and non-graphic, suitable for general audiences, "
    "no gore, no blood, no nudity, no explicit violence"
)

# Prefijo para el reintento cuando el primero se bloquea.
_SANITIZE_PREFIX = (
    "Symbolic, artistic and strictly non-graphic interpretation. Convey the "
    "drama only through atmosphere, shadows, silhouettes and facial expression "
    "— never show blood, wounds, nudity or explicit violence. Scene: "
)


def _is_moderation(exc: Exception) -> bool:
    s = str(exc).lower()
    return "moderation_blocked" in s or "safety system" in s or "safety_violations" in s


class OpenAIImageProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _generate_once(self, prompt: str, out_path: Path) -> Path:
        result = client().images.generate(
            model=self.settings.image_model,
            prompt=prompt,
            size="1024x1536",  # retrato (2:3), el más cercano a 9:16 disponible
            quality=self.settings.image_quality,
            n=1,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(result.data[0].b64_json))
        return out_path

    def generate(self, prompt: str, out_path: Path) -> Path:
        attempts = [
            prompt + _STYLE_SUFFIX,
            _SANITIZE_PREFIX + prompt + _STYLE_SUFFIX,
        ]
        last_exc: Exception | None = None
        for p in attempts:
            try:
                return self._generate_once(p, out_path)
            except Exception as exc:  # noqa: BLE001
                if _is_moderation(exc):
                    last_exc = exc
                    continue  # reintenta suavizado
                raise  # otros errores (red, cuota…) sí propagan
        raise ImageBlockedError(str(last_exc))
