"""Muestras de voz pregrabadas para escuchar cada voz sin generar un reel.

Se cachean en `assets/voice_samples/<voz>.mp3`. Se generan una vez (CLI
`python -m pressforge voices` o de forma perezosa al pedirlas desde la web).
"""
from __future__ import annotations

from pathlib import Path

from .registry import get_voice_provider

VOICES = ["onyx", "nova", "echo", "fable", "shimmer", "alloy", "ash", "ballad", "coral", "sage"]

SAMPLE_TEXT = (
    "Así sonará la narración de tus reels. Una historia que parece imposible… "
    "pero ocurrió de verdad."
)

SAMPLES_DIR = Path("assets/voice_samples")


def sample_path(voice: str) -> Path:
    return SAMPLES_DIR / f"{voice}.mp3"


def ensure_sample(voice: str) -> Path:
    """Devuelve la muestra de la voz, generándola si no existe."""
    path = sample_path(voice)
    if not path.exists():
        get_voice_provider().synthesize(SAMPLE_TEXT, path, voice=voice)
    return path


def generate_all(force: bool = False) -> list[str]:
    done = []
    for v in VOICES:
        p = sample_path(v)
        if force and p.exists():
            p.unlink()
        ensure_sample(v)
        done.append(v)
    return done
