"""Generador de 'brand kit' por marca: logo(s) + banners para cada red.

gpt-image-1 solo da 1024x1024 / 1024x1536 / 1536x1024. Así que generamos una
imagen base ancha y la recortamos con FFmpeg a las medidas exactas de cada
plataforma (YouTube, Facebook, Instagram, X). El logo cuadrado sirve de foto de
perfil en todas.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg
from .providers._openai_client import client

BRANDING_DIR = Path("assets/branding")

# Banners derivados de la imagen base (clave, ancho, alto, etiqueta).
_BANNERS = [
    ("youtube_banner", 2048, 1152, "Banner YouTube (2048×1152)"),
    ("facebook_cover", 1640, 856, "Portada Facebook (1640×856)"),
    ("x_header", 1500, 500, "Cabecera X/Twitter (1500×500)"),
    ("instagram_post", 1080, 1080, "Post/portada Instagram (1080×1080)"),
]

_NO_TEXT = "centered, iconic, high contrast, tasteful, no text, no letters, no watermark"


def _slug(name: str, maxlen: int = 40) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen] or "marca").strip("-")


def _gen(prompt: str, size: str, out: Path, quality: str = "high") -> None:
    r = client().images.generate(model="gpt-image-1", prompt=prompt, size=size, quality=quality, n=1)
    out.write_bytes(base64.b64decode(r.data[0].b64_json))


def _crop(src: Path, w: int, h: int, out: Path) -> None:
    run_ffmpeg(["-i", str(src), "-vf",
                f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", str(out)])


def _asset_entry(slug: str, key: str, label: str, w: int, h: int, is_logo: bool) -> dict:
    return {"key": key, "label": label, "filename": f"{slug}-{key}.png",
            "url": f"/assets/branding/{slug}/{key}.png", "w": w, "h": h, "logo": is_logo}


def list_kit(name: str) -> dict:
    """Brand kit YA generado para una marca (si existe en disco). Mismo formato
    que `generate_brand_kit`, pero solo con los archivos presentes."""
    slug = _slug(name)
    d = BRANDING_DIR / slug
    assets = []
    if (d / "logo_1.png").exists():
        assets.append(_asset_entry(slug, "logo_1", "Logo opción A (perfil)", 1024, 1024, True))
    if (d / "logo_2.png").exists():
        assets.append(_asset_entry(slug, "logo_2", "Logo opción B (perfil)", 1024, 1024, True))
    for key, w, h, label in _BANNERS:
        if (d / f"{key}.png").exists():
            assets.append(_asset_entry(slug, key, label, w, h, False))
    return {"slug": slug, "assets": assets}


def generate_brand_kit(name: str, niche: str = "", style: str = "") -> dict:
    slug = _slug(name)
    d = BRANDING_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    theme = (niche or name).strip()
    style = (style or "").strip()

    logo_base = (
        f"Professional emblem logo inspired by {theme}. "
        f"ONE single bold iconic symbol centered inside a circular golden badge with a thin "
        f"ornamental ring (laurel or greek-key). Flat vector emblem, thick clean lines, "
        f"generous negative space, SIMPLE and uncluttered — not a collage of many objects, "
        f"a single focal element. Premium gold-on-deep-dark color scheme, dramatic rim "
        f"lighting, crisp and highly legible at very small sizes. "
        f"{style + '. ' if style else ''}{_NO_TEXT}."
    )
    _gen(logo_base + " Choose the most iconic single symbol; bold and heroic.",
         "1024x1024", d / "logo_1.png")
    _gen(logo_base + " A DIFFERENT single symbol; elegant minimal line-art emblem.",
         "1024x1024", d / "logo_2.png")

    hero = d / "_hero.png"
    _gen(
        f"Wide cinematic channel banner background about {theme}. Epic dramatic scene, "
        f"golden divine volumetric light rays breaking through, atmospheric depth, fog and "
        f"shadows, subtle relevant scenery and silhouettes, rich moody dark tones, premium "
        f"cinematic color grading. Keep a clear darker EMPTY space in the CENTER for a title. "
        f"Ultra-wide composition. {style + '. ' if style else ''}{_NO_TEXT}.",
        "1536x1024", hero,
    )

    assets = [
        {"key": "logo_1", "label": "Logo opción A (perfil)", "filename": f"{slug}-logo-A.png",
         "url": f"/assets/branding/{slug}/logo_1.png", "w": 1024, "h": 1024, "logo": True},
        {"key": "logo_2", "label": "Logo opción B (perfil)", "filename": f"{slug}-logo-B.png",
         "url": f"/assets/branding/{slug}/logo_2.png", "w": 1024, "h": 1024, "logo": True},
    ]
    for key, w, h, label in _BANNERS:
        _crop(hero, w, h, d / f"{key}.png")
        assets.append({"key": key, "label": label, "filename": f"{slug}-{key}.png",
                       "url": f"/assets/branding/{slug}/{key}.png", "w": w, "h": h, "logo": False})

    return {"slug": slug, "assets": assets}
