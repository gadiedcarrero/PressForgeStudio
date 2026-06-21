"""Skybot — sección privada: a partir de la descripción de una NAVE, genera con
una plantilla FIJA (solo cambia la descripción entre naves):

  1. Imagen(es) de la nave en el hangar (2 variantes para elegir).
  2. Video en LOOP perfecto: la nave volando en el espacio entre meteoritos
     (último frame conecta con el primero → vuelo infinito).
  3. Video de presentación: SECUENCIA — puertas cerradas → se abren con humo y
     oscuridad → la nave sale → más ángulos hasta cubrir la narración. Con voz
     (ElevenLabs ES/EN) + música de fondo opcional.

Todo LOCAL (ComfyUI imágenes + LTX video), look cinematográfico sci-fi fijo.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import get_settings, output_path
from .ffmpeg_utils import ffprobe_duration, run_ffmpeg
from .registry import get_image_provider

_STYLE = "cinematic"
_SCIFI = "highly detailed sci-fi spaceship, intricate panels, dramatic lighting, cinematic, 8k"


def _slug(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen] or "nave").strip("-")


# ─── helpers de video ───
def _seamless_loop(raw: Path, out: Path, cross: float = 0.8) -> None:
    """Convierte un clip en LOOP perfecto: funde el principio sobre el final, así
    el último frame enlaza con el primero y se reproduce infinito sin saltos."""
    total = ffprobe_duration(raw)
    if total <= cross + 0.4:  # demasiado corto: déjalo tal cual
        run_ffmpeg(["-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
        return
    shift = total - cross
    fc = (
        f"[0]trim=0:{cross},setpts=PTS-STARTPTS,format=yuva420p,"
        f"fade=t=in:st=0:d={cross}:alpha=1,setpts=PTS+{shift}/TB[head];"
        f"[0]trim={cross}:{total},setpts=PTS-STARTPTS[body];"
        f"[body][head]overlay=eof_action=pass[v]"
    )
    run_ffmpeg(["-i", str(raw), "-filter_complex", fc, "-map", "[v]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", str(out)])


def _concat(clips: list[Path], out: Path) -> None:
    """Une varios mp4 (mismo tamaño/fps) en uno."""
    lst = out.with_name(out.stem + "_list.txt")
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", str(out)])
    lst.unlink(missing_ok=True)


def _music_path(name: str) -> Path | None:
    """Resuelve la pista de música elegida (de tu biblioteca local)."""
    if not name or name.lower() in ("none", "", "no"):
        return None
    try:
        from .registry import get_music_provider
        return get_music_provider().get_track(track=name)
    except Exception:  # noqa: BLE001
        return None


def _make_audio(workdir: Path, stem: str, text: str, voice_id: str,
                music: Path | None) -> tuple[Path, float] | None:
    """Genera el audio del reveal: voz (ElevenLabs) + música de fondo opcional.
    Devuelve (ruta_mp3, duración) o None si no hay voz."""
    if not (text.strip() and voice_id.strip()):
        return None
    from .providers.elevenlabs_voice import ElevenLabsVoiceProvider
    voice_mp3 = workdir / f"_{stem}_voice.mp3"
    ElevenLabsVoiceProvider().synthesize(text.strip(), voice_mp3, voice=voice_id)
    dur = ffprobe_duration(voice_mp3)
    if not music:
        return voice_mp3, dur
    vol = get_settings().music_volume
    out = workdir / f"_{stem}_mix.mp3"
    run_ffmpeg([
        "-i", str(voice_mp3), "-stream_loop", "-1", "-i", str(music),
        "-filter_complex", f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
        "-map", "[a]", "-t", f"{dur:.3f}", str(out),
    ])
    voice_mp3.unlink(missing_ok=True)
    return out, dur


def _build_reveal(intro: list[Path], angles: list[Path], out: Path,
                  audio: tuple[Path, float] | None, music: Path | None) -> None:
    """Arma el reveal: intro (puertas+salida) + ángulos repetidos hasta cubrir el
    audio (sin congelar). Mezcla la voz/música. Si no hay voz, una pasada."""
    if audio:
        audio_mp3, target = audio
        seq = list(intro)
        dur = sum(ffprobe_duration(c) for c in intro)
        i = 0
        while dur < target and angles:  # rellena con ÁNGULOS, no congela ni repite puertas
            clip = angles[i % len(angles)]
            seq.append(clip)
            dur += ffprobe_duration(clip)
            i += 1
        merged = out.with_name(out.stem + "_seq.mp4")
        _concat(seq, merged)
        run_ffmpeg([
            "-i", str(merged), "-i", str(audio_mp3), "-t", f"{target:.3f}",
            "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", str(out),
        ])
        merged.unlink(missing_ok=True)
        audio_mp3.unlink(missing_ok=True)
    else:
        merged = out.with_name(out.stem + "_seq.mp4")
        _concat(intro + angles, merged)
        if music:  # solo música de fondo (sin voz)
            vol = get_settings().music_volume
            target = ffprobe_duration(merged)
            run_ffmpeg([
                "-i", str(merged), "-stream_loop", "-1", "-i", str(music), "-t", f"{target:.3f}",
                "-filter_complex", f"[1:a]volume={vol}[a]", "-map", "0:v", "-map", "[a]",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out),
            ])
            merged.unlink(missing_ok=True)
        else:
            merged.replace(out)


def produce_skybot(description: str, on_event: Callable[[str], None] | None = None, *,
                   name: str = "", narration_es: str = "", narration_en: str = "",
                   voice_es: str = "", voice_en: str = "", music: str = "") -> dict:
    """Genera las piezas de Skybot para una nave. Devuelve rutas web /output/."""
    desc = description.strip()
    if not desc:
        raise ValueError("Describe la nave primero.")

    def ev(msg: str) -> None:
        if on_event:
            on_event(msg)

    from .providers.comfyui_video import image_to_video

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output_path() / "skybot" / f"{stamp}-{_slug(name or desc)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "_prompt.txt").write_text(desc, encoding="utf-8")
    if name.strip():
        (workdir / "_name.txt").write_text(name.strip(), encoding="utf-8")
    img = get_image_provider("local")
    base = workdir.name
    music_p = _music_path(music)

    def gen(prompt: str, fn: str) -> Path:
        p = workdir / fn
        img.generate(f"{desc}, a {_SCIFI}, {prompt}", p, style=_STYLE)
        return p

    def clip(image: Path, motion: str, fn: str, loop=False) -> Path:
        c = workdir / fn
        image_to_video(image, c, prompt=motion, duration="6", loop=loop, on_event=on_event)
        return c

    # ── 1. Imágenes de la nave en el hangar (2 variantes para elegir) ──
    ev("1/4 · Imágenes de la nave en el hangar…")
    images = []
    for i in (1, 2):
        images.append(gen("parked inside a futuristic spaceship hangar bay, industrial "
                          "lighting, wide cinematic shot", f"hangar_{i}.png"))

    # ── 2. Loop perfecto: la nave volando en el espacio ──
    ev("2/4 · Loop espacio (sin costuras)…")
    space = gen("flying through deep space among floating asteroids and meteorites, "
                "stars and colorful nebula background, dynamic cinematic angle", "_space.png")
    raw_loop = workdir / "_loop_raw.mp4"
    image_to_video(space, raw_loop,
                   prompt="the spaceship flies forward through the asteroid field, meteorites "
                          "drifting past, engine glow, smooth cinematic motion",
                   duration="6", loop=False, on_event=on_event)
    _seamless_loop(raw_loop, workdir / "space_loop.mp4")
    raw_loop.unlink(missing_ok=True)

    # ── 3. Secuencia del reveal (intro: puertas+humo+salida · ángulos extra) ──
    ev("3/4 · Secuencia de presentación (puertas → humo → la nave sale)…")
    door_img = gen("inside a massive futuristic hangar with huge closed bay doors, "
                   "thick smoke and darkness, dramatic volumetric light at the edges", "_door.png")
    intro = [
        clip(door_img, "the giant hangar bay doors slowly slide open revealing only thick "
                       "smoke and darkness inside, dramatic light beams, cinematic", "_c0.mp4"),
        clip(door_img, "the spaceship slowly emerges from the smoke and darkness of the hangar, "
                       "moving forward toward the camera, cinematic reveal", "_c1.mp4"),
    ]
    a1 = gen("flying in space, slow cinematic orbit, low dramatic angle, stars behind", "_a1.png")
    a2 = gen("flying in space, side profile tracking shot, engine glow, nebula behind", "_a2.png")
    angles = [
        clip(a1, "slow cinematic orbit around the spaceship, smooth camera motion", "_a1.mp4"),
        clip(a2, "smooth tracking shot following the spaceship from the side, cinematic", "_a2.mp4"),
    ]

    title = (name or "").strip()
    result = {
        "dir": base, "description": desc, "name": title,
        "images": [f"/output/skybot/{base}/{p.name}" for p in images],
        "image": f"/output/skybot/{base}/{images[0].name}",
        "loop": f"/output/skybot/{base}/space_loop.mp4",
    }

    # ── 4. Reveal con voz (ES/EN) + música ──
    have_es = narration_es.strip() and voice_es.strip()
    have_en = narration_en.strip() and voice_en.strip()
    if have_es:
        ev("· Reveal español (voz ElevenLabs + música)…")
        _build_reveal(intro, angles, workdir / "reveal_es.mp4",
                      _make_audio(workdir, "es", narration_es, voice_es, music_p), music_p)
        result["reveal_es"] = f"/output/skybot/{base}/reveal_es.mp4"
    if have_en:
        ev("· Reveal inglés (voz ElevenLabs + música)…")
        _build_reveal(intro, angles, workdir / "reveal_en.mp4",
                      _make_audio(workdir, "en", narration_en, voice_en, music_p), music_p)
        result["reveal_en"] = f"/output/skybot/{base}/reveal_en.mp4"
    if not have_es and not have_en:
        _build_reveal(intro, angles, workdir / "reveal.mp4", None, music_p)
        result["reveal"] = f"/output/skybot/{base}/reveal.mp4"

    ev("✓ Skybot listo")
    return result


def list_skybot() -> list[dict]:
    """Lista las naves generadas (más recientes primero), con TODOS sus assets."""
    root = output_path() / "skybot"
    out = []
    if root.exists():
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True):
            imgs = sorted(p.name for p in d.glob("*.png") if not p.name.startswith("_"))
            if not imgs:
                continue
            web = lambda fn: f"/output/skybot/{d.name}/{fn}"
            name = (d / "_name.txt").read_text(encoding="utf-8").strip() if (d / "_name.txt").exists() else ""
            desc = (d / "_prompt.txt").read_text(encoding="utf-8") if (d / "_prompt.txt").exists() else ""
            videos = {k: web(f) for k, f in
                      [("loop", "space_loop.mp4"), ("reveal_es", "reveal_es.mp4"),
                       ("reveal_en", "reveal_en.mp4"), ("reveal", "reveal.mp4")]
                      if (d / f).exists()}
            out.append({
                "dir": d.name, "name": name, "description": desc,
                "images": [web(i) for i in imgs], **videos,
            })
    return out
