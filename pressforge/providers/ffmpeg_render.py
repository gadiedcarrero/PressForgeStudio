"""RenderProvider con FFmpeg.

Tres pasos:
  1. Cada imagen -> clip vertical con efecto Ken Burns (zoom/pan suave + fades).
  2. Concatena los clips en un montaje sin audio.
  3. Quema los subtítulos ASS y mezcla narración (+ música opcional).

Se ejecuta con cwd = workdir y se referencian los archivos por nombre, para
evitar el infierno de escapar rutas de Windows en el filtro `ass`.
"""
from __future__ import annotations

from pathlib import Path

from ..ffmpeg_utils import ffprobe_duration, run_ffmpeg
from ..models import RenderJob, Scene

_VIDEO_FADE = 1.0   # s de fundido a negro al final
_MUSIC_FADE = 2.0   # s de fundido del sonido de la música al final
_TALK_TAIL = 2.0    # s de cola (último fotograma congelado) tras la voz en modo video


def render_talking(base_video: Path, subtitles_path: Path, out_path: Path, *,
                   music_path: Path | None = None, width: int = 1080,
                   height: int = 1920, fps: int = 30, music_volume: float = 0.12) -> Path:
    """Monta un reel a partir de un video de presentador (con su voz): ajusta a
    9:16, quema subtítulos, mezcla música y añade cola + fundidos."""
    wd = out_path.parent
    base = Path(base_video)
    dur = ffprobe_duration(base)
    total = dur + _TALK_TAIL
    v_st = max(0.0, total - _VIDEO_FADE)
    subs = subtitles_path.name

    # Vídeo: rellenar 9:16 (crop centrado), subtítulos, congelar último frame en
    # la cola y fundido a negro.
    video_chain = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},ass={subs},"
        f"tpad=stop_mode=clone:stop_duration={_TALK_TAIL},"
        f"fade=t=out:st={v_st:.3f}:d={_VIDEO_FADE},setsar=1,format=yuv420p[v]"
    )
    if music_path is not None:
        m_st = max(0.0, total - _MUSIC_FADE)
        audio_filter = (
            f"[0:a]apad[narr];"
            f"[1:a]volume={music_volume},aloop=loop=-1:size=2e9,"
            f"afade=t=out:st={m_st:.3f}:d={_MUSIC_FADE}[mus];"
            f"[narr][mus]amix=inputs=2:duration=longest:dropout_transition=0[a]"
        )
        filter_complex = f"{video_chain};{audio_filter}"
    else:
        filter_complex = f"{video_chain};[0:a]apad[a]"

    run_ffmpeg(
        [
            "-i", str(base.resolve()),
            *(["-i", str(music_path.resolve())] if music_path else []),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-r", str(fps), "-t", f"{total:.3f}",
            out_path.name,
        ],
        cwd=wd,
    )
    return out_path


def _kenburns_filter(scene: Scene, *, w: int, h: int, fps: int) -> str:
    tf = max(2, int(round(scene.duration * fps)))
    fade = 0.35
    fade_out_st = max(0.0, scene.duration - fade)
    # Alterna zoom-in / zoom-out por escena para dar variedad.
    if scene.index % 2 == 0:
        zoom = f"min(1.0+0.18*on/{tf},1.18)"
    else:
        zoom = f"max(1.18-0.18*on/{tf},1.0)"
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"scale={int(w * 1.5)}:{int(h * 1.5)},"
        f"zoompan=z='{zoom}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={tf}:s={w}x{h}:fps={fps},"
        f"fade=t=in:st=0:d={fade},"
        f"fade=t=out:st={fade_out_st:.3f}:d={fade},"
        f"setsar=1,format=yuv420p"
    )


class FFmpegRenderProvider:
    def render(self, job: RenderJob) -> Path:
        wd = job.workdir
        clips: list[str] = []

        # 1. Un clip Ken Burns por escena.
        for scene in job.scenes:
            if scene.image_path is None:
                continue
            tf = max(2, int(round(scene.duration * job.fps)))
            clip_name = f"clip_{scene.index:02d}.mp4"
            run_ffmpeg(
                [
                    "-i", str(scene.image_path.resolve()),
                    "-vf", _kenburns_filter(scene, w=job.width, h=job.height, fps=job.fps),
                    "-frames:v", str(tf),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", str(job.fps), "-an",
                    clip_name,
                ],
                cwd=wd,
            )
            clips.append(clip_name)

        if not clips:
            raise RuntimeError("No hay clips para renderizar (faltan imágenes).")

        # 2. Concatenar.
        concat_list = wd / "concat.txt"
        concat_list.write_text(
            "".join(f"file '{c}'\n" for c in clips), encoding="utf-8"
        )
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "montage.mp4"],
            cwd=wd,
        )

        # 3. Subtítulos + audio + fundidos de cierre.
        # Duración total = la del montaje (incluye la cola tras la voz). La voz
        # acaba antes; rellenamos con silencio y bajamos vídeo y música al final.
        total = sum(
            max(2, int(round(s.duration * job.fps)))
            for s in job.scenes if s.image_path is not None
        ) / job.fps
        v_st = max(0.0, total - _VIDEO_FADE)
        subs = job.subtitles_path.name
        video_chain = f"[0:v]ass={subs},fade=t=out:st={v_st:.3f}:d={_VIDEO_FADE}[v]"

        if job.music_path is not None:
            m_st = max(0.0, total - _MUSIC_FADE)
            audio_filter = (
                f"[1:a]apad[narr];"
                f"[2:a]volume={job.music_volume},aloop=loop=-1:size=2e9,"
                f"afade=t=out:st={m_st:.3f}:d={_MUSIC_FADE}[mus];"
                f"[narr][mus]amix=inputs=2:duration=longest:dropout_transition=0[a]"
            )
            filter_complex = f"{video_chain};{audio_filter}"
            maps = ["-map", "[v]", "-map", "[a]"]
        else:
            filter_complex = f"{video_chain};[1:a]apad[a]"
            maps = ["-map", "[v]", "-map", "[a]"]

        run_ffmpeg(
            [
                "-i", "montage.mp4", "-i", str(job.audio_path.resolve()),
                *(["-i", str(job.music_path.resolve())] if job.music_path else []),
                "-filter_complex", filter_complex,
                *maps,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-r", str(job.fps), "-t", f"{total:.3f}",
                job.output_path.name,
            ],
            cwd=wd,
        )
        return job.output_path
