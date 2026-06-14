"""Utilidades finas sobre ffmpeg / ffprobe."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def ffprobe_duration(path: Path) -> float:
    """Duración en segundos de un archivo de audio/vídeo."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def run_ffmpeg(args: list[str], cwd: Path | None = None) -> None:
    """Ejecuta ffmpeg y, si falla, levanta error con el stderr para diagnóstico."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}):\n{proc.stderr.strip()}"
        )
