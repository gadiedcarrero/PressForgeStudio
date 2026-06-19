"""Orquestador del pipeline V1: nicho -> reel.mp4.

Encadena los providers en orden y guarda todos los artefactos intermedios en
una carpeta de trabajo por reel (output/<timestamp>-<slug>/), para poder
inspeccionar/depurar cada paso.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from rich.console import Console

from .config import data_path, get_settings, output_path
from .ffmpeg_utils import ffprobe_duration, run_ffmpeg
from .providers.base import ImageBlockedError
from .models import RenderJob, ReelResult, Scene, Story
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

_MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def human_date(day: int, month: int, year: int | None) -> str:
    base = f"{day} de {_MONTHS_ES[month - 1]}"
    return f"{base} de {year}" if year else base


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


def _fallback_image(path, last_image, image_provider, idx, total, console, on_event) -> None:
    """Cuando una imagen se bloquea por seguridad: reutiliza la anterior, o genera
    una neutral, o en último caso un fondo sólido. El reel nunca se cae por esto."""
    msg = f"    ⚠ imagen {idx + 1}/{total} bloqueada por seguridad"
    # 1) Reutiliza la última imagen válida (continuidad visual, sin coste).
    if last_image and Path(last_image).exists():
        shutil.copy(last_image, path)
        note = f"{msg}; reutilizo la anterior"
    else:
        # 2) Imagen neutral garantizada-segura.
        try:
            image_provider.generate(
                "dark cinematic atmospheric background, moody dramatic lighting, "
                "fog and shadows, abstract, no people", path,
            )
            note = f"{msg}; uso una alternativa neutral"
        except Exception:  # noqa: BLE001
            # 3) Fondo sólido vía ffmpeg (sin API), por si todo falla.
            run_ffmpeg(["-f", "lavfi", "-i", "color=c=0x0d1117:s=1024x1536", "-frames:v", "1", str(path)])
            note = f"{msg}; uso un fondo sólido"
    console.print(f"    [yellow]{note}[/]")
    if on_event:
        on_event(note)


def _with_characters(prompt: str, names: list[str], descriptions: dict[str, str]) -> str:
    """Añade al prompt la descripción fija de los personajes de la escena, para
    que salgan iguales en todas las imágenes donde aparecen.

    Las escenas simbólicas/de objeto ya traen "no people" escrito por el guionista
    (lo pide la doctrina), así que aquí no hace falta adivinar nada."""
    parts = [descriptions[n] for n in names if descriptions.get(n)]
    if not parts:
        return prompt
    who = "; ".join(parts)
    return (f"{prompt}. The recurring character(s) must keep the SAME face and "
            f"identity as: {who}. Keep the face recognizable across scenes; their "
            f"clothing and body follow THIS scene's description (these may change "
            f"between scenes). Do NOT add any other people who are not described here.")


def _save_montage_cfg(workdir: Path, music: str | None) -> None:
    """Guarda la música elegida para poder REANUDAR el montaje si falla."""
    import json
    (workdir / "_montage.json").write_text(
        json.dumps({"music": music or ""}, ensure_ascii=False), encoding="utf-8")


def _finalize_narration(text: str) -> str:
    """Asegura que el texto que va a TTS cierre con puntuación final fuerte, para
    que la voz baje el tono al terminar (no suene a 'sigo hablando')."""
    text = text.strip()
    if text and text[-1] not in ".!?…":
        text += "."
    return text


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

# Segundos de "cola" que el vídeo continúa tras acabar la voz (outro con fundido).
_OUTRO_TAIL = 2.5

# Duración objetivo del reel → palabras de narración (español ≈ 2.4 pal/s reales).
# corto ~30s · medio ~45s · largo 60-90s (para calificar/monetizar en TikTok).
_DURATION_WORDS = {"short": 75, "medium": 115, "long": 200}


def duration_target_words(duration: str | None) -> int:
    return _DURATION_WORDS.get((duration or "medium").lower(), 150)


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
    target_words: int | None = None,
    language: str | None = None,
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
        return provider.refine(user_script, scenes=scenes, extra=extra, language=language)
    # mode == "invent"
    if not niche or not niche.strip():
        raise ValueError("El modo 'Inventar' necesita un nicho/tema.")
    return provider.generate(niche, scenes=scenes, extra=extra,
                             target_words=target_words, language=language)


def generate_story_from_fact(fact, *, scenes: int = 6, extra: str | None = None,
                             target_words: int | None = None, language: str | None = None) -> Story:
    """Guion fiel a un hecho real (Wikipedia/Reddit)."""
    return get_script_provider().from_source(fact, scenes=scenes, extra=extra,
                                             target_words=target_words, language=language)


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
    duration: str | None = None,
    dialogue: bool = False,
    language: str | None = None,
) -> list[Story]:
    """Devuelve una o varias propuestas de guion según el modo, para que el
    usuario elija/edite antes de producir.

    `scenes`: nº de imágenes; si es None/0 se calcula automáticamente según la
    longitud. `duration`: short/medium/long → palabras objetivo de narración.
    `language`: idioma de salida del guion/voz (ej. 'Spanish', 'English')."""
    count = max(1, min(3, count))
    tw = duration_target_words(duration)
    eff = scenes if (scenes and scenes > 0) else auto_scene_count(
        mode=mode, user_script=user_script, expected_words=tw)

    if mode == "mine":
        if not user_script or not user_script.strip():
            raise ValueError("El modo 'Mi guion' necesita un texto.")
        if dialogue:
            return [get_script_provider().dialogue(user_script, extra=extra, language=language)]
        return [generate_story(mode="mine", user_script=user_script, scenes=eff,
                               extra=extra, language=language)]

    if mode == "historic":
        if not niche or not niche.strip():
            raise ValueError("El modo 'Histórico' necesita un tema a buscar.")
        facts = get_research_provider().search(niche, limit=count)
        if not facts:
            raise ValueError(f"No encontré artículos en Wikipedia para «{niche}».")
        return [generate_story_from_fact(f, scenes=eff, extra=extra, target_words=tw,
                                         language=language) for f in facts]

    if mode == "onthisday":
        today = datetime.now()
        m = month or today.month
        d = day or today.day
        events = get_research_provider().on_this_day(m, d)
        if not events:
            raise ValueError("No encontré efemérides para esa fecha.")
        idxs = get_script_provider().select_events(events, theme=niche or "", count=count)
        stories = []
        for i in idxs:
            story = generate_story_from_fact(events[i], scenes=eff, extra=extra,
                                             target_words=tw, language=language)
            story.source_date = human_date(d, m, events[i].year)
            stories.append(story)
        return stories

    # mode == "invent"
    return [
        generate_story(mode="invent", niche=niche, scenes=eff, extra=extra,
                       target_words=tw, language=language)
        for _ in range(count)
    ]


# ─── Paso 2 (pesado): producir el reel desde un guion (ya editado) ───────────
def produce_reel(
    story: Story,
    *,
    music: str | None = None,
    voice: str | None = None,
    animate: bool = False,
    video_model: str = "kling-i2v",
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
    workdir = output_path() / f"{stamp}-{_slug(story.niche or story.title)}"
    (workdir / "images").mkdir(parents=True, exist_ok=True)
    _save_montage_cfg(workdir, music)

    # --- 1. Imágenes ---
    step("[bold cyan]1/5[/] Generando imágenes…", "1/5 · Generando imágenes…")
    image_provider = get_image_provider()
    char_desc = {c.name: c.description for c in story.characters if c.description.strip()}
    refs_dir = data_path() / "refs"
    last_image: Path | None = None
    n = len(story.scenes)
    for scene in story.scenes:
        path = workdir / "images" / f"scene_{scene.index:02d}.png"
        ref = refs_dir / scene.reference if scene.reference else None
        ref = ref if (ref and ref.is_file()) else None
        # Con referencia, la foto define la composición/personas; sin ella, se
        # inyecta la descripción fija de los personajes etiquetados.
        prompt = scene.image_prompt if ref else _with_characters(scene.image_prompt, scene.characters, char_desc)
        try:
            image_provider.generate(prompt, path, reference=ref)
            last_image = path
            console.print(f"    [green]✓[/] escena {scene.index + 1}/{n}")
            if on_event:
                on_event(f"    ✓ imagen {scene.index + 1}/{n}")
        except ImageBlockedError:
            _fallback_image(path, last_image, image_provider, scene.index, n, console, on_event)
            last_image = path
        scene.image_path = path

    # --- 2. Voz ---
    step("[bold cyan]2/5[/] Generando narración…", "2/5 · Generando narración…")
    narration = _finalize_narration(story.full_narration)
    audio_path = get_voice_provider().synthesize(narration, workdir / "narration.mp3")
    total = ffprobe_duration(audio_path)
    _assign_durations(story, total)
    # Cola tras la voz: el vídeo sigue unos segundos (con fundido) para no cortar
    # en seco al acabar la narración.
    if story.scenes:
        story.scenes[-1].duration += _OUTRO_TAIL
    console.print(f"    [green]✓[/] {total:.1f}s de audio")
    if on_event:
        on_event(f"    ✓ {total:.1f}s de audio")

    # --- 2.5 Animación (modo Video animado completo): cada escena → clip con movimiento ---
    if animate:
        from .providers.fal_video import image_to_video
        step("[bold cyan]·[/] Animando escenas (fal, puede tardar varios minutos)…",
             "· Animando escenas (fal, puede tardar varios minutos)…")
        for scene in story.scenes:
            if scene.image_path is None:
                continue
            dur_opt = "10" if scene.duration > 6 else "5"
            motion = (scene.image_prompt +
                      ", subtle natural motion, gentle cinematic camera movement, smooth, high quality")
            clip = workdir / "clips" / f"scene_{scene.index:02d}.mp4"
            try:
                image_to_video(scene.image_path, clip, prompt=motion,
                               duration=dur_opt, model=video_model, on_event=on_event)
                scene.clip_path = clip
                if on_event:
                    on_event(f"    ✓ escena {scene.index + 1}/{n} animada")
            except Exception as exc:  # noqa: BLE001 — si una falla, esa escena queda como imagen fija
                console.print(f"    [yellow]escena {scene.index + 1} sin animar:[/] {exc}")
                if on_event:
                    on_event(f"    ⚠ escena {scene.index + 1} sin animar (queda fija)")

    # --- 3. Subtítulos ---
    step("[bold cyan]3/5[/] Transcribiendo para subtítulos…", "3/5 · Transcribiendo para subtítulos…")
    words = get_subtitle_provider().transcribe(audio_path, language=story.language)
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

    final_path = workdir / "reel.mp4"
    job = RenderJob(
        workdir=workdir,
        scenes=story.scenes,
        audio_path=audio_path,
        subtitles_path=subs_path,
        output_path=final_path,
        music_path=music_path,
        width=settings.video_width,
        height=settings.video_height,
        fps=settings.fps,
        music_volume=settings.music_volume,
    )
    get_render_provider().render(job)
    step("[bold cyan]5/5[/] [green]✓ Reel listo[/]", "5/5 · ✓ Reel listo")

    return ReelResult(story=story, video_path=final_path, workdir=workdir, duration=total)


# ─── Paso 2 (alternativo): reel con PRESENTADOR 3D que habla (video IA) ──────
def produce_talking_reel(
    story: Story,
    *,
    presenter: str | None = None,
    music: str | None = None,
    voice: str | None = None,
    model: str = "kling-avatar",
    console: Console | None = None,
    on_event: Callable[[str], None] | None = None,
) -> ReelResult:
    """Genera un reel donde un personaje 3D narra hablando (lip-sync vía fal),
    con subtítulos + música + outro montados encima."""
    from .providers.fal_video import talking_avatar
    from .providers.ffmpeg_render import render_talking

    settings = get_settings()
    if voice:
        settings.voice_name = voice
    console = console or Console()

    def step(rich_msg: str, plain_msg: str) -> None:
        console.print(rich_msg)
        if on_event:
            on_event(plain_msg)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output_path() / f"{stamp}-{_slug(story.niche or story.title)}-talk"
    workdir.mkdir(parents=True, exist_ok=True)
    _save_montage_cfg(workdir, music)

    # 1. Presentador (imagen de frente, buena para lip-sync).
    step("[bold cyan]1/5[/] Generando presentador 3D…", "1/5 · Generando presentador 3D…")
    base_prompt = (presenter or "").strip() or (
        f"a friendly charismatic presenter for a channel about {story.niche or story.title}")
    presenter_prompt = (base_prompt + ", upper body, looking straight at the camera, "
                        "warm confident expression, centered portrait, simple clean background")
    pres_img = workdir / "presenter.png"
    get_image_provider().generate(presenter_prompt, pres_img)

    # 2. Voz (una sola narración continua).
    step("[bold cyan]2/5[/] Generando narración…", "2/5 · Generando narración…")
    narration = _finalize_narration(story.full_narration)
    audio_path = get_voice_provider().synthesize(narration, workdir / "narration.mp3")
    total = ffprobe_duration(audio_path)
    console.print(f"    [green]✓[/] {total:.1f}s de audio")
    if on_event:
        on_event(f"    ✓ {total:.1f}s de audio")

    # 3. Animar al presentador (fal: imagen + audio → video hablando).
    step("[bold cyan]3/5[/] Animando al presentador (puede tardar 1-3 min)…",
         "3/5 · Animando al presentador (puede tardar 1-3 min)…")
    talking = talking_avatar(pres_img, audio_path, workdir / "talking.mp4",
                             model=model, on_event=on_event)

    # 4. Subtítulos (sobre la misma narración).
    step("[bold cyan]4/5[/] Transcribiendo para subtítulos…", "4/5 · Transcribiendo para subtítulos…")
    words = get_subtitle_provider().transcribe(audio_path, language=story.language)
    subs_path = build_ass(words, workdir / "subs.ass",
                          width=settings.video_width, height=settings.video_height)

    _save_story(story, workdir, total)

    # 5. Montaje final: subtítulos + música + outro (cola + fundidos) sobre el video.
    step("[bold cyan]5/5[/] Montaje final (subtítulos + música + outro)…",
         "5/5 · Montaje final (subtítulos + música + outro)…")
    music_path = _resolve_music(music, story.music_mood or story.niche)
    if music_path and on_event:
        on_event(f"    ♪ música: {music_path.name}")
    final_path = workdir / "reel.mp4"
    render_talking(talking, subs_path, final_path, music_path=music_path,
                   width=settings.video_width, height=settings.video_height,
                   fps=settings.fps, music_volume=settings.music_volume)
    step("[bold cyan]✓[/] [green]Reel listo[/]", "✓ Reel listo")
    return ReelResult(story=story, video_path=final_path, workdir=workdir, duration=total)


# ─── Paso 2 (diálogo): cada escena, un personaje habla con su voz (lip-sync) ──
def produce_dialogue_reel(
    story: Story,
    *,
    music: str | None = None,
    voice: str | None = None,
    engine: str = "veo3",
    console: Console | None = None,
    on_event: Callable[[str], None] | None = None,
) -> ReelResult:
    """Reel de diálogo. Dos motores:
    - 'veo3': Veo 3.1 genera cada escena con audio + lip-sync NATIVO (mejor para
      2+ personajes; las voces las pone Veo). Más caro.
    - 'omnihuman': la voz de cada personaje (ElevenLabs) + OmniHuman anima al que
      habla (ideal cuando habla UNO por escena; más barato)."""
    from .providers.fal_video import talking_avatar, veo3_dialogue
    from .providers.ffmpeg_render import aligned_voice, concat_audio, extract_audio
    from .providers.elevenlabs_voice import ElevenLabsVoiceProvider

    settings = get_settings()
    console = console or Console()

    def step(rich_msg: str, plain_msg: str) -> None:
        console.print(rich_msg)
        if on_event:
            on_event(plain_msg)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output_path() / f"{stamp}-{_slug(story.niche or story.title)}-dlg"
    (workdir / "images").mkdir(parents=True, exist_ok=True)
    (workdir / "clips").mkdir(parents=True, exist_ok=True)
    (workdir / "audio").mkdir(parents=True, exist_ok=True)
    _save_montage_cfg(workdir, music)

    char_desc = {c.name: c.description for c in story.characters if c.description.strip()}
    char_voice = {c.name: c.voice for c in story.characters if c.voice.strip()}
    vp = ElevenLabsVoiceProvider()  # voz fija por personaje (consistencia en todo el reel)
    image_provider = get_image_provider()

    # Imágenes MAESTRAS de referencia por personaje: cara fija que se reusa en cada
    # escena (consistencia de rostro en todo el reel). La ropa de cada momento la
    # pone el prompt de cada escena (el guion arrastra los cambios de vestuario).
    refs_dir = workdir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    char_ref: dict[str, Path] = {}
    if story.characters:
        step("[bold cyan]0/4[/] Imágenes maestras de personajes…",
             "0/4 · Imágenes maestras de personajes…")
        for c in story.characters:
            rp = refs_dir / f"{_slug(c.name)}.png"
            try:
                image_provider.generate(
                    f"Full-body character reference sheet of {c.description}. Standing, "
                    f"front view, full body visible, neutral plain light-gray studio "
                    f"background.", rp)
                char_ref[c.name] = rp
                if on_event:
                    on_event(f"    ✓ referencia: {c.name}")
            except Exception:  # noqa: BLE001
                pass
    lang_name = story.language or settings.language

    # AUDIO PRIMERO: una línea por escena; la voz la pone ElevenLabs (voz FIJA por
    # personaje → misma voz en todo el reel). Veo genera SOLO el video (sin audio),
    # moviendo los labios con la línea; luego se monta la voz de ElevenLabs encima.
    n = len(story.scenes)
    label = "Veo 3 (video) + ElevenLabs" if engine == "veo3" else "OmniHuman + ElevenLabs"
    step(f"[bold cyan]1-2/4[/] Imágenes + {label} por escena (fal, tarda)…",
         f"1-2/4 · Imágenes + {label} por escena (puede tardar)…")

    render_scenes: list[Scene] = []
    audio_parts: list[Path] = []
    last_image: Path | None = None
    for sc in story.scenes:
        ui = sc.index
        chars_in = [c for c in sc.characters if c]
        img = workdir / "images" / f"scene_{ui:02d}.png"
        clip = workdir / "clips" / f"scene_{ui:02d}.mp4"
        line_audio = workdir / "audio" / f"line_{ui:02d}.mp3"

        # imagen de la escena usando las referencias maestras (misma cara) + la
        # ropa/acción actual del prompt (el guion arrastra los cambios de vestuario)
        try:
            refs = [char_ref[c] for c in chars_in if c in char_ref]
            scene_prompt = _with_characters(sc.image_prompt, chars_in, char_desc)
            image_provider.generate_with_refs(scene_prompt, refs, img)
            last_image = img
        except ImageBlockedError:
            _fallback_image(img, last_image, image_provider, ui, n, console, on_event)
            last_image = img

        unit = Scene(index=ui, narration=sc.narration, image_prompt=sc.image_prompt,
                     characters=chars_in, speaker=sc.speaker, image_path=img)
        try:
            v = char_voice.get(sc.speaker) or voice or None
            if engine == "veo3":
                # Veo genera el video CON su audio (sabe hablar). Luego: transcribimos
                # los TIEMPOS del habla de Veo y generamos la voz de ElevenLabs ajustada
                # a esos tiempos → voz consistente sincronizada con los labios de Veo.
                others = [c for c in chars_in if c != sc.speaker]
                others_txt = (f" {', '.join(others)} listens silently with mouth closed, "
                              f"reacting with gestures." if others else "")
                wn = len(sc.narration.split())
                dur = "8s" if wn > 9 else ("6s" if wn > 4 else "4s")
                veo_prompt = (
                    f"{sc.image_prompt}. {sc.speaker} says in {lang_name}: \"{sc.narration}\"."
                    f"{others_txt} Pixar/Disney 3D animated movie style, expressive faces, "
                    f"accurate lip-sync, natural motion, cinematic camera.")
                # Veo a veces rechaza un prompt (no_media_generated). Si pasa,
                # reintenta con un prompt más simple (menos probable que lo bloquee).
                simple_prompt = (
                    f"{sc.speaker} speaks a line in {lang_name}, talking to another person. "
                    f"3D animated movie style, expressive face, natural lip movement.")
                try:
                    veo3_dialogue(img, clip, prompt=veo_prompt, duration=dur, audio=True, on_event=on_event)
                except Exception:  # noqa: BLE001
                    if on_event:
                        on_event(f"    · Veo reintenta con prompt simple…")
                    veo3_dialogue(img, clip, prompt=simple_prompt, duration=dur, audio=True, on_event=on_event)
                clip_dur = ffprobe_duration(clip)
                # tiempos del habla de Veo
                veo_audio = workdir / "audio" / f"veo_{ui:02d}.mp3"
                extract_audio(clip, veo_audio)
                try:
                    words = get_subtitle_provider().transcribe(veo_audio, language=story.language)
                except Exception:  # noqa: BLE001
                    words = []
                if words:
                    offset = max(0.0, words[0].start)
                    speech_dur = max(0.3, words[-1].end - words[0].start)
                else:
                    offset, speech_dur = 0.0, clip_dur
                # voz consistente (ElevenLabs) ajustada a esos tiempos
                raw = workdir / "audio" / f"raw_{ui:02d}.mp3"
                vp.synthesize(sc.narration, raw, voice=v)
                aligned_voice(raw, line_audio, offset_s=offset,
                              speech_dur=speech_dur, total_dur=clip_dur)
                unit.duration = clip_dur
            else:  # omnihuman: el audio (ElevenLabs) guía el lip-sync directamente
                vp.synthesize(sc.narration, line_audio, voice=v)
                talking_avatar(img, line_audio, clip, model="omnihuman", on_event=on_event)
                unit.duration = ffprobe_duration(clip)
            unit.clip_path = clip
            audio_parts.append(line_audio)
            if on_event:
                on_event(f"    ✓ escena {ui + 1}/{n} ({sc.speaker}) lista")
        except Exception as exc:  # noqa: BLE001 — fallback: voz sobre imagen fija
            console.print(f"    [yellow]escena {ui + 1} sin video ({exc}); imagen fija[/]")
            if line_audio.is_file():
                unit.duration = ffprobe_duration(line_audio)
                audio_parts.append(line_audio)
            else:
                unit.duration = 3.0
            if on_event:
                on_event(f"    ⚠ escena {ui + 1} sin video (queda fija)")
        render_scenes.append(unit)

    if not audio_parts:
        raise RuntimeError("No se generó ninguna escena (revisa tu fal API key/saldo).")

    story.scenes = render_scenes  # las unidades pasan a ser las escenas del reel

    # Audio continuo + cola.
    audio_path = concat_audio(audio_parts, workdir / "narration.mp3")
    total = ffprobe_duration(audio_path)
    if render_scenes:
        render_scenes[-1].duration += _OUTRO_TAIL

    # 3. Subtítulos (transcribiendo el audio real del reel).
    step("[bold cyan]3/4[/] Subtítulos…", "3/4 · Transcribiendo para subtítulos…")
    words = get_subtitle_provider().transcribe(audio_path, language=story.language)
    subs_path = build_ass(words, workdir / "subs.ass",
                          width=settings.video_width, height=settings.video_height)
    _save_story(story, workdir, total)

    # 4. Montaje (reusa el render: concat de clips + voz + subs + música + outro).
    step("[bold cyan]4/4[/] Montaje final…", "4/4 · Montaje final (subtítulos + música + outro)…")
    music_path = _resolve_music(music, story.music_mood or story.niche)
    if music_path and on_event:
        on_event(f"    ♪ música: {music_path.name}")
    final_path = workdir / "reel.mp4"
    job = RenderJob(
        workdir=workdir, scenes=story.scenes, audio_path=audio_path,
        subtitles_path=subs_path, output_path=final_path, music_path=music_path,
        width=settings.video_width, height=settings.video_height,
        fps=settings.fps, music_volume=settings.music_volume,
    )
    get_render_provider().render(job)
    step("[bold cyan]✓[/] [green]Reel listo[/]", "✓ Reel listo")
    return ReelResult(story=story, video_path=final_path, workdir=workdir, duration=total)


# ─── Reanudar el montaje final desde una carpeta ya generada ─────────────────
def resume_render(workdir: Path, *, music: str | None = None) -> Path:
    """Re-hace SOLO el montaje final (concat + voz + subtítulos + música + outro)
    desde una carpeta con clips/imágenes/narración/subs ya generados (p. ej. si
    el render falló por memoria). No vuelve a llamar a fal ni a la IA."""
    import json

    settings = get_settings()
    data = json.loads((workdir / "story.json").read_text(encoding="utf-8"))

    def _p(v):
        return Path(v) if v and v != "None" else None

    scenes = []
    for i, s in enumerate(data.get("scenes", [])):
        scenes.append(Scene(
            index=s.get("index", i), narration=s.get("narration", ""),
            image_prompt=s.get("image_prompt", ""), characters=list(s.get("characters") or []),
            speaker=s.get("speaker", "") or "", image_path=_p(s.get("image_path")),
            clip_path=_p(s.get("clip_path")), duration=float(s.get("duration") or 0),
        ))
    story = Story(niche=data.get("niche", ""), title=data.get("title", ""),
                  hook=data.get("hook", ""), cta=data.get("cta", ""), scenes=scenes)

    # Música: la del montaje guardado (_montage.json) salvo override explícito.
    if music is None:
        try:
            music = json.loads((workdir / "_montage.json").read_text(encoding="utf-8")).get("music") or None
        except Exception:  # noqa: BLE001
            music = None
    audio_path = workdir / "narration.mp3"
    subs_path = workdir / "subs.ass"
    music_path = _resolve_music(music, story.niche) if music else None
    final_path = workdir / "reel.mp4"
    job = RenderJob(
        workdir=workdir, scenes=scenes, audio_path=audio_path, subtitles_path=subs_path,
        output_path=final_path, music_path=music_path, width=settings.video_width,
        height=settings.video_height, fps=settings.fps, music_volume=settings.music_volume,
    )
    get_render_provider().render(job)
    return final_path


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
        "characters": [{"name": c.name, "description": c.description} for c in story.characters],
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
