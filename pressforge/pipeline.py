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


def generate_reel(
    niche: str,
    *,
    scenes: int = 6,
    extra: str | None = None,
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
        """Loguea a la consola (CLI) y emite el evento limpio (Web UI)."""
        console.print(rich_msg)
        if on_event:
            on_event(plain_msg)

    # --- Carpeta de trabajo ---
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = _OUTPUT_ROOT / f"{stamp}-{_slug(niche)}"
    (workdir / "images").mkdir(parents=True, exist_ok=True)

    # --- 1. Guion + storyboard ---
    step("[bold cyan]1/6[/] Generando guion y storyboard…", "1/6 · Generando guion y storyboard…")
    story = get_script_provider().generate(niche, scenes=scenes, extra=extra)
    console.print(f"    [green]✓[/] «{story.title}» · {len(story.scenes)} escenas")
    console.print(f"    [dim]Hook:[/] {story.hook}")
    if on_event:
        on_event(f"    ✓ «{story.title}» · {len(story.scenes)} escenas")

    # --- 2. Imágenes ---
    step("[bold cyan]2/6[/] Generando imágenes…", "2/6 · Generando imágenes…")
    image_provider = get_image_provider()
    for scene in story.scenes:
        path = workdir / "images" / f"scene_{scene.index:02d}.png"
        image_provider.generate(scene.image_prompt, path)
        scene.image_path = path
        msg = f"    ✓ imagen {scene.index + 1}/{len(story.scenes)}"
        console.print(f"    [green]✓[/] escena {scene.index + 1}/{len(story.scenes)}")
        if on_event:
            on_event(msg)

    # --- 3. Voz ---
    step("[bold cyan]3/6[/] Generando narración…", "3/6 · Generando narración…")
    audio_path = get_voice_provider().synthesize(story.full_narration, workdir / "narration.mp3")
    total = ffprobe_duration(audio_path)
    _assign_durations(story, total)
    console.print(f"    [green]✓[/] {total:.1f}s de audio")
    if on_event:
        on_event(f"    ✓ {total:.1f}s de audio")

    # --- 4. Subtítulos ---
    step("[bold cyan]4/6[/] Transcribiendo para subtítulos…", "4/6 · Transcribiendo para subtítulos…")
    words = get_subtitle_provider().transcribe(audio_path)
    subs_path = build_ass(words, workdir / "subs.ass", width=settings.video_width, height=settings.video_height)
    console.print(f"    [green]✓[/] {len(words)} palabras sincronizadas")
    if on_event:
        on_event(f"    ✓ {len(words)} palabras sincronizadas")

    # --- 5. Persistir guion ---
    _save_story(story, workdir, total)

    # --- 6. Render ---
    step(
        "[bold cyan]5/6[/] Renderizando vídeo (Ken Burns + subtítulos + audio)…",
        "5/6 · Renderizando vídeo (Ken Burns + subtítulos + audio)…",
    )
    music_path = _resolve_music(music, story.music_mood or niche)
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
    step("[bold cyan]6/6[/] [green]✓ Reel listo[/]", "6/6 · ✓ Reel listo")

    return ReelResult(story=story, video_path=output_path, workdir=workdir, duration=total)


def _save_story(story: Story, workdir: Path, duration: float) -> None:
    data = {
        "niche": story.niche,
        "title": story.title,
        "hook": story.hook,
        "cta": story.cta,
        "duration_s": duration,
        "full_narration": story.full_narration,
        "scenes": [asdict(s) | {"image_path": str(s.image_path) if s.image_path else None}
                   for s in story.scenes],
    }
    # asdict ya incluye image_path como Path; lo normalizamos a str arriba.
    (workdir / "story.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
