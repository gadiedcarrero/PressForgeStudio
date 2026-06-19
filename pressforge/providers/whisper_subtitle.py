"""SubtitleProvider con Whisper.

Transcribe el audio YA generado por la voz IA para obtener timestamps por
palabra. Así los subtítulos quedan perfectamente sincronizados con lo que de
verdad suena (en vez de estimar tiempos sobre el texto del guion).
"""
from __future__ import annotations

from pathlib import Path

from ..config import get_settings
from ..models import Word
from ._openai_client import client

# Nombre de idioma (como lo usa el guion) → código ISO-639-1 que espera Whisper.
_ISO = {
    "spanish": "es", "español": "es", "espanol": "es", "es": "es",
    "english": "en", "inglés": "en", "ingles": "en", "en": "en",
}


def _to_iso(language: str | None, fallback: str) -> str:
    """'English'/'Spanish'/'en'/… → 'en'/'es'. Si no se reconoce, usa fallback."""
    if not language:
        return fallback
    key = language.strip().lower()
    return _ISO.get(key, fallback if len(key) != 2 else key)


class WhisperSubtitleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[Word]:
        # El audio lo generamos nosotros, así que sabemos su idioma: lo pasamos a
        # Whisper para que NO transcriba inglés como español fonético (y viceversa).
        iso = _to_iso(language, self.settings.language)
        with open(audio_path, "rb") as f:
            transcript = client().audio.transcriptions.create(
                model=self.settings.subtitle_model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
                language=iso,
            )
        words = getattr(transcript, "words", None) or []
        return [
            Word(text=w.word, start=float(w.start), end=float(w.end))
            for w in words
        ]
