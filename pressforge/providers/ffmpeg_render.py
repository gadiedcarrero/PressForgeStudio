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

from ..ffmpeg_utils import run_ffmpeg
from ..models import RenderJob, Scene


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

        # 3. Subtítulos + audio.
        subs = job.subtitles_path.name
        if job.music_path is not None:
            audio_filter = (
                f"[2:a]volume={job.music_volume},aloop=loop=-1:size=2e9[mus];"
                f"[1:a][mus]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
            filter_complex = f"[0:v]ass={subs}[v];{audio_filter}"
            maps = ["-map", "[v]", "-map", "[a]"]
        else:
            filter_complex = f"[0:v]ass={subs}[v]"
            maps = ["-map", "[v]", "-map", "1:a"]

        run_ffmpeg(
            [
                "-i", "montage.mp4", "-i", str(job.audio_path.resolve()),
                *(["-i", str(job.music_path.resolve())] if job.music_path else []),
                "-filter_complex", filter_complex,
                *maps,
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-r", str(job.fps), "-shortest",
                job.output_path.name,
            ],
            cwd=wd,
        )
        return job.output_path
