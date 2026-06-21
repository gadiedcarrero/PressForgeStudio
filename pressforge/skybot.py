"""Skybot — sección privada: a partir de la descripción de una NAVE, genera con
una plantilla FIJA tres piezas (solo cambia la descripción entre naves):

  1. Imagen: la nave en el hangar.
  2. Video en loop: la nave volando en el espacio entre meteoritos.
  3. Video 3D cinematográfico: unas puertas se abren y la nave sale.

Todo LOCAL (ComfyUI para imágenes + LTX para video), con look cinematográfico
sci-fi fijo (no depende del 'Estilo visual' que tengas elegido para los reels).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import output_path
from .registry import get_image_provider

_STYLE = "cinematic"  # look fijo sci-fi/cinematográfico para todas las naves
_SCIFI = "highly detailed sci-fi spaceship, intricate panels, dramatic lighting, cinematic, 8k"


def _slug(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen] or "nave").strip("-")


def produce_skybot(description: str, on_event: Callable[[str], None] | None = None) -> dict:
    """Genera las 3 piezas de Skybot para una nave. Devuelve rutas web /output/."""
    desc = description.strip()
    if not desc:
        raise ValueError("Describe la nave primero.")

    def ev(msg: str) -> None:
        if on_event:
            on_event(msg)

    from .providers.comfyui_video import image_to_video

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output_path() / "skybot" / f"{stamp}-{_slug(desc)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "_prompt.txt").write_text(desc, encoding="utf-8")
    img = get_image_provider("local")
    base = workdir.name

    # ── 1. Imagen: la nave en el hangar ──
    ev("1/3 · Imagen de la nave en el hangar…")
    hangar = workdir / "hangar.png"
    img.generate(
        f"{desc}, a {_SCIFI}, parked inside a futuristic spaceship hangar bay, "
        f"industrial lighting, wide cinematic shot",
        hangar, style=_STYLE,
    )

    # ── 2. Video loop: la nave volando en el espacio entre meteoritos ──
    ev("2/3 · Video en loop: la nave en el espacio…")
    space = workdir / "_space.png"
    img.generate(
        f"{desc}, a {_SCIFI}, flying through deep space among floating asteroids and "
        f"meteorites, stars and colorful nebula background, dynamic cinematic angle",
        space, style=_STYLE,
    )
    loop_mp4 = workdir / "space_loop.mp4"
    image_to_video(
        space, loop_mp4,
        prompt="the spaceship flies forward through the asteroid field, meteorites "
               "drifting past, engine glow, subtle cinematic camera motion, smooth",
        duration="6", loop=True, on_event=on_event,
    )

    # ── 3. Video 3D cinematográfico: puertas que se abren y la nave sale ──
    ev("3/3 · Video cinematográfico: puertas que se abren…")
    door = workdir / "_door.png"
    img.generate(
        f"{desc}, a {_SCIFI}, inside a massive futuristic hangar with huge bay doors "
        f"beginning to open, bright volumetric light pouring through the gap, "
        f"dramatic cinematic reveal, the ship facing the camera",
        door, style=_STYLE,
    )
    reveal_mp4 = workdir / "reveal.mp4"
    image_to_video(
        door, reveal_mp4,
        prompt="the giant hangar bay doors slide open and the spaceship slowly flies "
               "forward out of the hangar toward the camera, cinematic reveal, smooth motion",
        duration="6", loop=False, on_event=on_event,
    )

    ev("✓ Skybot listo")
    return {
        "dir": base,
        "description": desc,
        "image": f"/output/skybot/{base}/hangar.png",
        "loop": f"/output/skybot/{base}/space_loop.mp4",
        "reveal": f"/output/skybot/{base}/reveal.mp4",
    }


def list_skybot() -> list[dict]:
    """Lista las naves ya generadas (más recientes primero)."""
    root = output_path() / "skybot"
    out = []
    if root.exists():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            if (d / "hangar.png").exists():
                desc = ""
                pf = d / "_prompt.txt"
                if pf.exists():
                    desc = pf.read_text(encoding="utf-8")
                out.append({
                    "dir": d.name, "description": desc,
                    "image": f"/output/skybot/{d.name}/hangar.png",
                    "loop": f"/output/skybot/{d.name}/space_loop.mp4" if (d / "space_loop.mp4").exists() else None,
                    "reveal": f"/output/skybot/{d.name}/reveal.mp4" if (d / "reveal.mp4").exists() else None,
                })
    return out
