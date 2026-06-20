"""SubtitleProvider LOCAL con faster-whisper. GRATIS en tu Mac.

Transcribe el audio ya generado para obtener timestamps por palabra, sin coste
ni llamadas a la nube. El modelo se descarga solo la primera vez (cache local).
Mismo resultado que el provider OpenAI (lista de Word con tiempos).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from ..models import Word
from .whisper_subtitle import _to_iso  # reutiliza el mapeo de idioma → ISO


@lru_cache(maxsize=2)
def _model(name: str):
    # CPU int8: rápido y compatible en Apple Silicon (CTranslate2 no usa MPS).
    from faster_whisper import WhisperModel
    return WhisperModel(name, device="cpu", compute_type="int8")


class LocalWhisperSubtitleProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def transcribe(self, audio_path: Path, language: str | None = None) -> list[Word]:
        iso = _to_iso(language, self.settings.language)
        model = _model(self.settings.local_whisper_model)
        segments, _ = model.transcribe(str(audio_path), language=iso, word_timestamps=True)
        words: list[Word] = []
        for seg in segments:
            for w in (seg.words or []):
                txt = (w.word or "").strip()
                if txt:
                    words.append(Word(text=txt, start=float(w.start), end=float(w.end)))
        return words
