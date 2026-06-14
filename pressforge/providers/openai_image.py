"""ImageProvider con gpt-image-1.

gpt-image-1 entrega el tamaño retrato más cercano a 9:16 (1024x1536). El render
se encarga después de escalar/recortar a 1080x1920 con el efecto Ken Burns.
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..config import get_settings
from ._openai_client import client

# Sufijo añadido a cada prompt para forzar formato y estilo consistentes.
_STYLE_SUFFIX = (
    ", cinematic historical realism, dramatic lighting, highly detailed, "
    "vertical 9:16 composition, no text, no watermark, no modern objects"
)


class OpenAIImageProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def generate(self, prompt: str, out_path: Path) -> Path:
        result = client().images.generate(
            model=self.settings.image_model,
            prompt=prompt + _STYLE_SUFFIX,
            size="1024x1536",  # retrato (2:3), el más cercano a 9:16 disponible
            quality=self.settings.image_quality,
            n=1,
        )
        b64 = result.data[0].b64_json
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(b64))
        return out_path
