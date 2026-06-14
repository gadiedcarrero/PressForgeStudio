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


class WhisperSubtitleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def transcribe(self, audio_path: Path) -> list[Word]:
        with open(audio_path, "rb") as f:
            transcript = client().audio.transcriptions.create(
                model=self.settings.subtitle_model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
                language=self.settings.language,
            )
        words = getattr(transcript, "words", None) or []
        return [
            Word(text=w.word, start=float(w.start), end=float(w.end))
            for w in words
        ]
