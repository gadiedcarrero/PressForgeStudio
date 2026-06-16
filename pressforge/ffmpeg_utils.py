"""Utilidades finas sobre ffmpeg / ffprobe.

Resuelve la ruta de los binarios aunque no estén en el PATH del proceso: mira el
PATH, luego la variable FFMPEG_DIR, y por último ubicaciones típicas de la
instalación (winget en Windows, Homebrew en Mac). Así el servidor funciona sin
depender de que lo arranques desde una terminal con el PATH "bueno".
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# Ubicaciones típicas donde buscar el ejecutable si no está en el PATH.
_SEARCH_GLOBS = [
    # Windows · winget (Gyan.FFmpeg)
    r"C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\ffmpeg\bin",
    # macOS · Homebrew
    "/opt/homebrew/bin",
    "/usr/local/bin",
    # Linux
    "/usr/bin",
]


@lru_cache(maxsize=8)
def _resolve(name: str) -> str:
    """Ruta absoluta al ejecutable `name` (ffmpeg/ffprobe), o el nombre pelado."""
    exe = name + (".exe" if os.name == "nt" else "")
    # 1) En el PATH.
    found = shutil.which(name) or shutil.which(exe)
    if found:
        return found
    # 2) FFMPEG_DIR explícito.
    env_dir = os.environ.get("FFMPEG_DIR")
    if env_dir and (Path(env_dir) / exe).is_file():
        return str(Path(env_dir) / exe)
    # 3) Ubicaciones típicas (glob; recursivo donde haga falta).
    import glob
    for pattern in _SEARCH_GLOBS:
        for d in glob.glob(pattern, recursive=True):
            cand = Path(d) / exe
            if cand.is_file():
                return str(cand)
    # 4) Sin suerte: devolver el nombre (fallará con mensaje claro).
    return name


def has_binary(name: str) -> bool:
    return _resolve(name) != name or shutil.which(name) is not None


def ffprobe_duration(path: Path) -> float:
    """Duración en segundos de un archivo de audio/vídeo."""
    out = subprocess.run(
        [
            _resolve("ffprobe"), "-v", "error",
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
        [_resolve("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg falló (código {proc.returncode}):\n{proc.stderr.strip()}"
        )
