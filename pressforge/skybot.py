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
from .registry import get_image_provider, get_script_provider

_STYLE = "cinematic"
_SCIFI = "highly detailed sci-fi spaceship, intricate panels, dramatic lighting, cinematic, 8k"


def _slug(text: str, maxlen: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:maxlen] or "nave").strip("-")


# ─── motor de imagen (consistencia de la nave) ───
# Etiqueta de cada vista para explicarle a los motores qué es cada imagen.
_VIEW_LABEL = {
    "front": "the FRONT view", "left": "the LEFT side view",
    "top": "the TOP-DOWN view", "perspective": "a 3/4 PERSPECTIVE view",
}


def _view_prefix(refs: list) -> str:
    """Explica a Seedance/OpenAI qué es cada imagen de referencia (@ImageN)."""
    if not refs:
        return ""
    parts = [f"@Image{i + 1} is {_VIEW_LABEL.get(v, 'a reference view')}"
             for i, (v, _) in enumerate(refs)]
    return ("; ".join(parts) + " — these are ALL the SAME spaceship from different "
            "angles. Keep that EXACT ship (identical design, colors, markings). ")


def _openai_edit(refs: list, scene: str, out: Path) -> None:
    """gpt-image-1: recrea la MISMA nave (1 o varias vistas de referencia)."""
    import base64
    from .providers._openai_client import client
    s = get_settings()
    multi = (" The reference images show the SAME spaceship from different angles."
             if len(refs) > 1 else "")
    prompt = (
        "Keep the EXACT same spaceship as in the reference image(s): identical design, "
        f"hull shape, proportions, colors, markings and details.{multi} Do not redesign it. "
        f"Now show that same spaceship {scene}. Cinematic sci-fi, dramatic lighting, "
        "9:16 vertical, no text, no watermark."
    )
    files = [open(p, "rb") for _, p in refs]
    try:
        r = client().images.edit(model=s.image_model, image=(files if len(files) > 1 else files[0]),
                                 prompt=prompt, size="1024x1536", quality=s.image_quality, n=1)
    finally:
        for f in files:
            f.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(r.data[0].b64_json))


def _scene_image(local_provider, desc: str, scene: str, out: Path,
                 engine: str, refs: list) -> Path:
    """Genera la imagen de una escena de la nave manteniendo la MISMA nave (con
    1 o varias vistas de referencia). OpenAI → edit; local → IP-Adapter."""
    paths = [p for _, p in refs]
    if engine == "openai" and refs:
        _openai_edit(refs, scene, out)
    elif refs:
        local_provider.generate(f"{desc}, a {_SCIFI}, {scene}", out,
                                reference=paths, style=_STYLE, subject=True)
    else:
        local_provider.generate(f"{desc}, a {_SCIFI}, {scene}", out, style=_STYLE)
    return out


def _animate(image: Path, out: Path, motion: str, engine: str, loop: bool, on_event) -> Path:
    """Anima una imagen base según el motor: 'local' (LTX) o un modelo de fal
    (kling-i2v / seedance / seedance2 …)."""
    if engine and engine != "local":
        from .providers.fal_video import image_to_video as fal_i2v
        fal_i2v(image, out, prompt=motion, duration="5", model=engine, on_event=on_event)
    else:
        from .providers.comfyui_video import image_to_video as ltx_i2v
        ltx_i2v(image, out, prompt=motion, duration="6", loop=loop, on_event=on_event)
    return out


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


def _reveal_shots(narration: str, desc: str, n: int) -> list[str]:
    """Saca un 'guion' de la narración (como modo Historia): una escena visual de
    la NAVE por cada cosa que se dice, para cubrir todo el audio sin repetir."""
    ship = f"the {desc} spaceship"
    fallback = [
        f"{ship} inside a massive hangar with bay doors opening, smoke and dramatic light beams",
        f"{ship} slowly emerging from the smoky dark hangar, moving toward the camera",
        f"{ship} flying out into deep space, stars and colorful nebula behind",
        f"close-up of {ship}'s engines igniting with a bright blue glow",
        f"{ship} banking in a dramatic cinematic orbit, low heroic angle",
        f"{ship} flying fast through a dense asteroid field, meteorites drifting past",
        f"side tracking shot of {ship} cruising through deep space",
        f"heroic front view of {ship} approaching the camera, lens flare",
    ]
    if narration.strip():
        try:
            story = get_script_provider().refine(narration, scenes=n)
            shots = [f"{ship}; {s.image_prompt}" for s in story.scenes if s.image_prompt.strip()]
            if len(shots) >= 2:
                while len(shots) < n:
                    shots.append(fallback[len(shots) % len(fallback)])
                return shots[:n]
        except Exception:  # noqa: BLE001 — si el guion falla, usa la secuencia fija
            pass
    return (fallback * ((n // len(fallback)) + 1))[:n]


def _reveal_from_clips(clips: list, out: Path, audio, music) -> None:
    """Concatena los clips de escena y les pone la voz (o música) cubriendo todo."""
    seq = out.with_name(out.stem + "_seq.mp4")
    _concat([c for c in clips if c and Path(c).is_file()], seq)
    if audio:
        audio_mp3, target = audio
        run_ffmpeg(["-stream_loop", "-1", "-i", str(seq), "-i", str(audio_mp3),
                    "-t", f"{target:.3f}", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)])
        audio_mp3.unlink(missing_ok=True)
    elif music:
        target = ffprobe_duration(seq)
        run_ffmpeg(["-i", str(seq), "-stream_loop", "-1", "-i", str(music), "-t", f"{target:.3f}",
                    "-filter_complex", f"[1:a]volume={get_settings().music_volume}[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out)])
    else:
        seq.replace(out)
    seq.unlink(missing_ok=True)


def produce_skybot(description: str, on_event: Callable[[str], None] | None = None, *,
                   name: str = "", narration_es: str = "", narration_en: str = "",
                   voice_es: str = "", voice_en: str = "", music: str = "",
                   image_engine: str = "local", video_engine: str = "local",
                   reference: str = "", references: list | None = None,
                   director: bool = False) -> dict:
    """Genera las piezas de Skybot para una nave. Devuelve rutas web /output/.

    image_engine: 'local' (ComfyUI) u 'openai' (gpt-image-1; con `reference`
      mantiene la MISMA nave entre escenas → consistencia).
    video_engine: 'local' (LTX) o 'fal' (Kling/Veo, de pago).
    reference: ruta a la imagen de la nave que ancla la consistencia."""
    desc = description.strip()
    if not desc:
        raise ValueError("Describe la nave primero.")
    # refs: lista ordenada de (vista, ruta) con las vistas que SÍ subiste
    # (front/left/top/perspective). Compatibilidad: `reference` = una sola.
    refs: list = []
    for r in (references or []):
        p = Path(r.get("path", ""))
        if r.get("path") and p.is_file():
            refs.append((r.get("view", "perspective"), p))
    if not refs and reference and Path(reference).is_file():
        refs = [("perspective", Path(reference))]

    def ev(msg: str) -> None:
        if on_event:
            on_event(msg)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output_path() / "skybot" / f"{stamp}-{_slug(name or desc)}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "_prompt.txt").write_text(desc, encoding="utf-8")
    if name.strip():
        (workdir / "_name.txt").write_text(name.strip(), encoding="utf-8")
    img = get_image_provider("local")
    base = workdir.name
    music_p = _music_path(music)
    # Si subiste vistas de referencia, guárdalas (son la nave exacta).
    if refs:
        import shutil
        for v, p in refs:
            shutil.copy(p, workdir / f"referencia_{v}.png")

    def gen(scene: str, fn: str) -> Path:
        return _scene_image(img, desc, scene, workdir / fn, image_engine, refs)

    def clip(image: Path, motion: str, fn: str, loop=False) -> Path:
        return _animate(image, workdir / fn, motion, video_engine, loop, on_event)

    # CONSISTENCIA: si no subiste ninguna vista, genera una nave MAESTRA desde la
    # descripción y úsala de referencia en TODO (hangar, loop, reveal) → misma nave.
    if not refs:
        ev("· Imagen maestra de la nave (desde tu descripción)…")
        master = workdir / "ship_master.png"
        _scene_image(img, desc, "full hero shot, the entire spaceship clearly visible, "
                     "three-quarter angle, neutral dark studio background", master, image_engine, [])
        refs = [("perspective", master)]  # gen()/ref_clip() la usan (late-binding)
    ref_paths = [p for _, p in refs]
    vpfx = _view_prefix(refs)  # explica las vistas a Seedance/OpenAI
    sd_ref = (video_engine == "seedance2-ref")

    def ref_clip(shot: str, fn: str, dur: str) -> Path:
        from .providers.fal_video import seedance_ref2video
        out = workdir / fn
        seedance_ref2video(ref_paths, out, prompt=f"{vpfx}Show that spaceship: {shot}",
                           duration=dur, audio=False, aspect_ratio="9:16", on_event=on_event)
        return out

    def scene_clip(shot: str, fn: str) -> Path:
        """Un clip de una escena (nave consistente vía referencia)."""
        if sd_ref:
            return ref_clip(f"{shot}, cinematic", fn, "5s")
        si = gen(shot, "_" + fn.replace(".mp4", ".png"))
        return clip(si, shot + ", cinematic camera motion, smooth", fn)

    # ── 1. Imágenes de la nave en el hangar (2 variantes para elegir) ──
    ev("1/4 · Imágenes de la nave en el hangar…")
    images = [gen("parked inside a futuristic spaceship hangar bay, industrial lighting, "
                  "wide cinematic shot", f"hangar_{i}.png") for i in (1, 2)]

    # ── 2. Loop perfecto: la nave volando en el espacio ──
    ev("2/4 · Loop espacio (sin costuras)…")
    raw_loop = workdir / "_loop_raw.mp4"
    scene_clip("flying forward through a dense asteroid field, meteorites drifting past, "
               "engine glow, deep space, nebula", "_loop_raw.mp4")
    _seamless_loop(raw_loop, workdir / "space_loop.mp4")
    raw_loop.unlink(missing_ok=True)

    title = (name or "").strip()
    result = {
        "dir": base, "description": desc, "name": title,
        "images": [f"/output/skybot/{base}/{p.name}" for p in images],
        "image": f"/output/skybot/{base}/{images[0].name}",
        "loop": f"/output/skybot/{base}/space_loop.mp4",
    }

    # ── 3. Reveal: AUDIO primero → escenas (guion) que CUBREN todo el audio ──
    have_es = narration_es.strip() and voice_es.strip()
    have_en = narration_en.strip() and voice_en.strip()
    audio_es = _make_audio(workdir, "es", narration_es, voice_es, music_p) if have_es else None
    audio_en = _make_audio(workdir, "en", narration_en, voice_en, music_p) if have_en else None
    target = max([a[1] for a in (audio_es, audio_en) if a] + [6.0])
    narr = narration_es.strip() or narration_en.strip()
    clip_len = 5.0 if (sd_ref or video_engine == "fal") else 2.3
    n_sc = max(2, min(9, int(target / clip_len) + 1))
    shots = None
    if director:  # Modo Director: dirección cinematográfica por toma (Dreamina-Octo)
        from .director import build_shot_prompt
        ev("· Modo Director: guion de rodaje de la nave…")
        brief = (f"Cinematic reveal of a spaceship. Main entity (keep IDENTICAL every "
                 f"shot): the spaceship — {desc}. Build a hangar-to-space reveal that "
                 f"covers this narration: {narr or 'a dramatic doors-open reveal then flight'}")
        try:
            ds = get_script_provider().direct(brief, shots=n_sc, dialogue=False,
                                              extra="VERTICAL 9:16 format (use aspect_ratio '9:16 vertical').")
            shots = [build_shot_prompt(ds, s, with_dialogue=False) for s in ds.shots] or None
        except Exception:  # noqa: BLE001 — si falla, secuencia normal
            shots = None
    if not shots:
        shots = _reveal_shots(narr, desc, n_sc)
    ev(f"3/4 · {len(shots)} escenas de presentación (cubren la narración)…")
    seq_clips = [scene_clip(sh, f"_rv{i}.mp4") for i, sh in enumerate(shots)]

    if have_es:
        ev("· Montando reveal español…")
        _reveal_from_clips(seq_clips, workdir / "reveal_es.mp4", audio_es, music_p)
        result["reveal_es"] = f"/output/skybot/{base}/reveal_es.mp4"
    if have_en:
        ev("· Montando reveal inglés…")
        _reveal_from_clips(seq_clips, workdir / "reveal_en.mp4", audio_en, music_p)
        result["reveal_en"] = f"/output/skybot/{base}/reveal_en.mp4"
    if not have_es and not have_en:
        _reveal_from_clips(seq_clips, workdir / "reveal.mp4", None, music_p)
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
