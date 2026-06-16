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
from ..secrets_store import get_secret
from .base import ImageBlockedError
from ._openai_client import client

# "Looks" visuales seleccionables (la parte estética del prompt). El usuario los
# elige en Crear; el de seguridad/formato se añade siempre por separado.
STYLES: dict[str, str] = {
    "cinematic": "cinematic historical realism, dramatic moody lighting, highly detailed, filmic color grade",
    "photo": "photorealistic, ultra-realistic, lifelike detail, natural lighting, shot on a 50mm lens, shallow depth of field",
    "vivid": "vibrant saturated colors, rich vivid color grading, bold dramatic lighting, high color contrast, eye-catching",
    "painting": "classical oil painting style, painterly visible brushwork, baroque fine-art look, warm tones",
    "illustration": "stylized digital illustration, clean shapes and lines, concept-art look, artistic",
    "vintage": "vintage aged photograph, sepia and faded tones, old archival film look, subtle grain",
    "anime": "anime / manga illustration style, cel shading, expressive, detailed background art",
    "3d": ("3D animated feature-film style (Pixar/Disney-like CGI), stylized characters "
           "with soft rounded features and big expressive faces, smooth subsurface-scattering "
           "skin, polished glossy render, warm cinematic lighting, shallow depth of field"),
}
DEFAULT_STYLE = "cinematic"

# Barandillas de formato + seguridad: SIEMPRE se añaden, sea cual sea el look.
_FORMAT_SAFETY = (
    ", vertical 9:16 composition, no text, no watermark, no modern objects, "
    "tasteful and non-graphic, suitable for general audiences, "
    "no gore, no blood, no nudity, no explicit violence"
)


def _style_suffix() -> str:
    key = (get_secret("image_style") or DEFAULT_STYLE).strip()
    look = STYLES.get(key, STYLES[DEFAULT_STYLE])
    return ", " + look + _FORMAT_SAFETY

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

    def _edit_once(self, prompt: str, reference: Path, out_path: Path) -> Path:
        with open(reference, "rb") as f:
            result = client().images.edit(
                model=self.settings.image_model,
                image=f,
                prompt=prompt,
                size="1024x1536",
                quality=self.settings.image_quality,
                n=1,
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(base64.b64decode(result.data[0].b64_json))
        return out_path

    def generate(self, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        suffix = _style_suffix()
        if reference and Path(reference).is_file():
            # Recrea la composición de la foto de referencia en el estilo elegido.
            base = ("Recreate the same composition, framing, poses, gestures and emotion "
                    "as the reference image, but redraw it completely in this style. "
                    + prompt)
            attempts = [base + suffix, _SANITIZE_PREFIX + base + suffix]
            gen = lambda p: self._edit_once(p, Path(reference), out_path)  # noqa: E731
        else:
            attempts = [prompt + suffix, _SANITIZE_PREFIX + prompt + suffix]
            gen = lambda p: self._generate_once(p, out_path)  # noqa: E731

        last_exc: Exception | None = None
        for p in attempts:
            try:
                return gen(p)
            except Exception as exc:  # noqa: BLE001
                if _is_moderation(exc):
                    last_exc = exc
                    continue  # reintenta suavizado
                raise  # otros errores (red, cuota…) sí propagan
        raise ImageBlockedError(str(last_exc))
