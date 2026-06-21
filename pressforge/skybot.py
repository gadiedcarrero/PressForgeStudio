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
from .ffmpeg_utils import ffprobe_duration, run_ffmpeg
from .registry import get_image_provider

_STYLE = "cinematic"  # look fijo sci-fi/cinematográfico para todas las naves
_SCIFI = "highly detailed sci-fi spaceship, intricate panels, dramatic lighting, cinematic, 8k"


def _slug(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen] or "nave").strip("-")


# Fuente para el título (primera que exista; Mac y Windows).
_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
]


def _font() -> str:
    for f in _FONTS:
        if Path(f).exists():
            return f
    return ""


def _title_filter(title: str, total: float, width: int = 512) -> str:
    """drawtext que muestra el NOMBRE de la nave casi al final, con fundido. El
    tamaño se adapta al largo del nombre para que SIEMPRE quepa en el ancho."""
    font = _font()
    safe = re.sub(r"[':\\%]", "", title).strip()
    if not font or not safe:
        return ""
    start = max(0.0, total - 2.6)  # aparece ~2.6 s antes del final
    fontsize = max(24, min(48, int(width * 1.45 / max(len(safe), 1))))
    esc = font.replace(":", r"\:").replace(" ", r"\ ")
    return (
        f"drawtext=fontfile={esc}:text='{safe}':fontsize={fontsize}:fontcolor=white:"
        f"box=1:boxcolor=black@0.5:boxborderw=12:borderw=2:bordercolor=black@0.8:"
        f"x=(w-text_w)/2:y=h*0.80:"
        f"enable='gte(t,{start:.2f})':"
        f"alpha='if(lt(t,{start:.2f}),0,min(1,(t-{start:.2f})/0.7))'"
    )


def _finish_reveal(silent: Path, out: Path, title: str = "",
                   text: str = "", voice_id: str = "") -> None:
    """Reveal final: narración (ElevenLabs, opcional) + título de la nave casi al
    final. Si hay narración, el video se extiende (congela el último frame) para
    cubrir el audio; si no, mantiene su duración."""
    if text.strip() and voice_id.strip():
        from .providers.elevenlabs_voice import ElevenLabsVoiceProvider
        audio = out.with_suffix(".mp3")
        ElevenLabsVoiceProvider().synthesize(text.strip(), audio, voice=voice_id)
        dur = ffprobe_duration(audio)
        vf = f"tpad=stop_mode=clone:stop_duration={dur:.3f},fps=25"
        tf = _title_filter(title, dur)
        if tf:
            vf += "," + tf
        run_ffmpeg([
            "-i", str(silent), "-i", str(audio),
            "-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]", "-map", "1:a",
            "-t", f"{dur:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(out),
        ])
        audio.unlink(missing_ok=True)
    else:  # sin narración: solo el título sobre el reveal mudo
        dur = ffprobe_duration(silent)
        vf = "fps=25"
        tf = _title_filter(title, dur)
        if tf:
            vf += "," + tf
        run_ffmpeg(["-i", str(silent), "-vf", vf, "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(out)])


def produce_skybot(description: str, on_event: Callable[[str], None] | None = None, *,
                   name: str = "", narration_es: str = "", narration_en: str = "",
                   voice_es: str = "", voice_en: str = "") -> dict:
    """Genera las 3 piezas de Skybot para una nave. Devuelve rutas web /output/.

    Si se da narración + voz (ES/EN), el video de presentación (reveal) se entrega
    también con audio narrado por ElevenLabs en ese idioma."""
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
    silent = workdir / "_reveal_silent.mp4"
    image_to_video(
        door, silent,
        prompt="the giant hangar bay doors slide open and the spaceship slowly flies "
               "forward out of the hangar toward the camera, cinematic reveal, smooth motion",
        duration="6", loop=False, on_event=on_event,
    )

    title = (name or "").strip()
    result = {
        "dir": base,
        "description": desc,
        "name": title,
        "image": f"/output/skybot/{base}/hangar.png",
        "loop": f"/output/skybot/{base}/space_loop.mp4",
    }

    # ── 4. Reveal final con título + narración (ElevenLabs) español / inglés ──
    have_es = narration_es.strip() and voice_es.strip()
    have_en = narration_en.strip() and voice_en.strip()
    if have_es:
        ev("· Reveal en español (voz ElevenLabs + título)…")
        _finish_reveal(silent, workdir / "reveal_es.mp4", title, narration_es, voice_es.strip())
        result["reveal_es"] = f"/output/skybot/{base}/reveal_es.mp4"
    if have_en:
        ev("· Reveal en inglés (voz ElevenLabs + título)…")
        _finish_reveal(silent, workdir / "reveal_en.mp4", title, narration_en, voice_en.strip())
        result["reveal_en"] = f"/output/skybot/{base}/reveal_en.mp4"
    if not have_es and not have_en:  # sin narración: reveal mudo con el título
        _finish_reveal(silent, workdir / "reveal.mp4", title)
        result["reveal"] = f"/output/skybot/{base}/reveal.mp4"

    ev("✓ Skybot listo")
    return result


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

                def _w(fn: str):
                    return f"/output/skybot/{d.name}/{fn}" if (d / fn).exists() else None

                out.append({
                    "dir": d.name, "description": desc,
                    "image": f"/output/skybot/{d.name}/hangar.png",
                    "loop": _w("space_loop.mp4"),
                    "reveal": _w("reveal.mp4"),
                    "reveal_es": _w("reveal_es.mp4"),
                    "reveal_en": _w("reveal_en.mp4"),
                })
    return out
