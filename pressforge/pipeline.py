"""Orquestador del pipeline V1: nicho -> reel.mp4.

Encadena los providers en orden y guarda todos los artefactos intermedios en
una carpeta de trabajo por reel (output/<timestamp>-<slug>/), para poder
inspeccionar/depurar cada paso.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console

from .config import get_settings
from .ffmpeg_utils import ffprobe_duration
from .models import RenderJob, ReelResult, Story
from .registry import (
    get_image_provider,
    get_music_provider,
    get_render_provider,
    get_research_provider,
    get_script_provider,
    get_subtitle_provider,
    get_voice_provider,
)
from .subtitles import build_ass

_OUTPUT_ROOT = Path("output")


def _slug(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen] or "reel").strip("-")


def _resolve_music(music: str | None, niche: str) -> Path | None:
    """Interpreta el valor de música:
    None/""/"none" → sin música · "auto" → el provider elige según el nicho ·
    ruta de archivo existente → esa · cualquier otro → nombre de pista en la
    biblioteca.
    """
    if not music or music.strip().lower() in ("none", "no", ""):
        return None
    music = music.strip()
    as_path = Path(music)
    if as_path.is_file():
        return as_path
    provider = get_music_provider()
    if music.lower() == "auto":
        return provider.get_track(mood=niche)
    return provider.get_track(track=music)


def _assign_durations(story: Story, total: float) -> None:
    """Reparte la duración total del audio entre escenas, proporcional a las
    palabras de cada narración."""
    weights = [max(1, len(s.narration.split())) for s in story.scenes]
    wsum = sum(weights)
    for scene, w in zip(story.scenes, weights):
        scene.duration = round(total * w / wsum, 3)


# Una imagen cada ~4 s de narración (≈ 11 palabras a ritmo de español).
_WORDS_PER_SCENE = 11
_MIN_SCENES, _MAX_SCENES = 4, 18


def auto_scene_count(*, mode: str, user_script: str | None = None, expected_words: int = 140) -> int:
    """Nº de escenas/imágenes en función de la longitud, no fijo.

    Más guion → más escenas (la imagen cambia cada ~4 s). En 'Mi guion' se
    estima por las palabras del texto del usuario; en el resto, por la longitud
    objetivo del guion generado.
    """
    if mode == "mine" and user_script and user_script.strip():
        words = len(user_script.split())
    else:
        words = expected_words
    return max(_MIN_SCENES, min(_MAX_SCENES, round(words / _WORDS_PER_SCENE)))


# ─── Paso 1 (rápido): generar el guion para revisar/editar ───────────────────
def generate_story(
    *,
    mode: str = "invent",
    niche: str | None = None,
    scenes: int = 6,
    extra: str | None = None,
    user_script: str | None = None,
) -> Story:
    """Devuelve solo el guion + storyboard (sin imágenes/voz/render).

    mode:
      - "invent": la IA inventa una historia a partir de `niche`.
      - "mine":   la IA pule/corrige el `user_script` sin inventar hechos.
    """
    provider = get_script_provider()
    if mode == "mine":
        if not user_script or not user_script.strip():
            raise ValueError("El modo 'Mi guion' necesita un texto de guion.")
        return provider.refine(user_script, scenes=scenes, extra=extra)
    # mode == "invent"
    if not niche or not niche.strip():
        raise ValueError("El modo 'Inventar' necesita un nicho/tema.")
    return provider.generate(niche, scenes=scenes, extra=extra)


def generate_story_from_fact(fact, *, scenes: int = 6, extra: str | None = None) -> Story:
    """Guion fiel a un hecho real (Wikipedia)."""
    return get_script_provider().from_source(fact, scenes=scenes, extra=extra)


def generate_stories(
    *,
    mode: str = "invent",
    niche: str | None = None,
    scenes: int | None = None,
    extra: str | None = None,
    user_script: str | None = None,
    count: int = 1,
    month: int | None = None,
    day: int | None = None,
) -> list[Story]:
    """Devuelve una o varias propuestas de guion según el modo, para que el
    usuario elija/edite antes de producir.

    `scenes`: nº de imágenes; si es None/0 se calcula automáticamente según la
    longitud (más guion → más escenas)."""
    count = max(1, min(3, count))
    eff = scenes if (scenes and scenes > 0) else auto_scene_count(mode=mode, user_script=user_script)

    if mode == "mine":
        return [generate_story(mode="mine", user_script=user_script, scenes=eff, extra=extra)]

    if mode == "historic":
        if not niche or not niche.strip():
            raise ValueError("El modo 'Histórico' necesita un tema a buscar.")
        facts = get_research_provider().search(niche, limit=count)
        if not facts:
            raise ValueError(f"No encontré artículos en Wikipedia para «{niche}».")
        return [generate_story_from_fact(f, scenes=eff, extra=extra) for f in facts]

    if mode == "onthisday":
        today = datetime.now()
        m = month or today.month
        d = day or today.day
        events = get_research_provider().on_this_day(m, d)
        if not events:
            raise ValueError("No encontré efemérides para esa fecha.")
        idxs = get_script_provider().select_events(events, theme=niche or "", count=count)
        return [generate_story_from_fact(events[i], scenes=eff, extra=extra) for i in idxs]

    # mode == "invent"
    return [
        generate_story(mode="invent", niche=niche, scenes=eff, extra=extra)
        for _ in range(count)
    ]


# ─── Paso 2 (pesado): producir el reel desde un guion (ya editado) ───────────
def produce_reel(
    story: Story,
    *,
    music: str | None = None,
    voice: str | None = None,
    console: Console | None = None,
    on_event: Callable[[str], None] | None = None,
) -> ReelResult:
    settings = get_settings()
    if voice:
        settings.voice_name = voice
    console = console or Console()

    def step(rich_msg: str, plain_msg: str) -> None:
        console.print(rich_msg)
        if on_event:
            on_event(plain_msg)

    # --- Carpeta de trabajo ---
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = _OUTPUT_ROOT / f"{stamp}-{_slug(story.niche or story.title)}"
    (workdir / "images").mkdir(parents=True, exist_ok=True)

    # --- 1. Imágenes ---
    step("[bold cyan]1/5[/] Generando imágenes…", "1/5 · Generando imágenes…")
    image_provider = get_image_provider()
    for scene in story.scenes:
        path = workdir / "images" / f"scene_{scene.index:02d}.png"
        image_provider.generate(scene.image_prompt, path)
        scene.image_path = path
        console.print(f"    [green]✓[/] escena {scene.index + 1}/{len(story.scenes)}")
        if on_event:
            on_event(f"    ✓ imagen {scene.index + 1}/{len(story.scenes)}")

    # --- 2. Voz ---
    step("[bold cyan]2/5[/] Generando narración…", "2/5 · Generando narración…")
    audio_path = get_voice_provider().synthesize(story.full_narration, workdir / "narration.mp3")
    total = ffprobe_duration(audio_path)
    _assign_durations(story, total)
    console.print(f"    [green]✓[/] {total:.1f}s de audio")
    if on_event:
        on_event(f"    ✓ {total:.1f}s de audio")

    # --- 3. Subtítulos ---
    step("[bold cyan]3/5[/] Transcribiendo para subtítulos…", "3/5 · Transcribiendo para subtítulos…")
    words = get_subtitle_provider().transcribe(audio_path)
    subs_path = build_ass(words, workdir / "subs.ass", width=settings.video_width, height=settings.video_height)
    console.print(f"    [green]✓[/] {len(words)} palabras sincronizadas")
    if on_event:
        on_event(f"    ✓ {len(words)} palabras sincronizadas")

    _save_story(story, workdir, total)

    # --- 4. Render ---
    step(
        "[bold cyan]4/5[/] Renderizando vídeo (Ken Burns + subtítulos + audio)…",
        "4/5 · Renderizando vídeo (Ken Burns + subtítulos + audio)…",
    )
    music_path = _resolve_music(music, story.music_mood or story.niche)
    if music:
        if music_path:
            mood = f" (mood: {story.music_mood})" if music.lower() == "auto" and story.music_mood else ""
            console.print(f"    [dim]Música:[/] {music_path.name}{mood}")
            if on_event:
                on_event(f"    ♪ música: {music_path.name}{mood}")
        else:
            console.print("    [yellow]Música no encontrada; sigo sin música.[/]")
            if on_event:
                on_event("    ♪ música no encontrada; sin música")

    output_path = workdir / "reel.mp4"
    job = RenderJob(
        workdir=workdir,
        scenes=story.scenes,
        audio_path=audio_path,
        subtitles_path=subs_path,
        output_path=output_path,
        music_path=music_path,
        width=settings.video_width,
        height=settings.video_height,
        fps=settings.fps,
        music_volume=settings.music_volume,
    )
    get_render_provider().render(job)
    step("[bold cyan]5/5[/] [green]✓ Reel listo[/]", "5/5 · ✓ Reel listo")

    return ReelResult(story=story, video_path=output_path, workdir=workdir, duration=total)


# ─── Conveniencia: guion + producción en un paso (usado por la CLI) ──────────
def generate_reel(
    niche: str,
    *,
    scenes: int | None = None,
    extra: str | None = None,
    music: str | None = None,
    voice: str | None = None,
    console: Console | None = None,
    on_event: Callable[[str], None] | None = None,
) -> ReelResult:
    if on_event:
        on_event("0/5 · Generando guion…")
    eff = scenes if (scenes and scenes > 0) else auto_scene_count(mode="invent")
    story = generate_story(mode="invent", niche=niche, scenes=eff, extra=extra)
    if console:
        console.print(f"[bold cyan]Guion[/] «{story.title}» · {len(story.scenes)} escenas")
    return produce_reel(story, music=music, voice=voice, console=console, on_event=on_event)


def _save_story(story: Story, workdir: Path, duration: float) -> None:
    data = {
        "niche": story.niche,
        "title": story.title,
        "hook": story.hook,
        "cta": story.cta,
        "source_title": story.source_title,
        "source_url": story.source_url,
        "duration_s": duration,
        "full_narration": story.full_narration,
        "scenes": [asdict(s) | {"image_path": str(s.image_path) if s.image_path else None}
                   for s in story.scenes],
    }
    # asdict ya incluye image_path como Path; lo normalizamos a str arriba.
    (workdir / "story.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
