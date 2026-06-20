"""VoiceProvider LOCAL con Kokoro (ONNX). GRATIS en tu Mac, sin torch ni nube.

TTS rápido (más rápido que tiempo real en CPU), con voces en español e inglés.
Calidad por debajo de ElevenLabs, pero muy decente y $0. El modelo se descarga
la primera vez a ~/.cache/pressforge/kokoro/.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from ..ffmpeg_utils import run_ffmpeg

_MODEL_DIR = Path.home() / ".cache" / "pressforge" / "kokoro"
_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

# Alias amigables → voz Kokoro (1ª letra = idioma: e=español, a=inglés US).
_ALIAS = {"dora": "ef_dora", "alex": "em_alex", "santa": "em_santa"}


def _ensure_models() -> tuple[Path, Path]:
    """Descarga el modelo + voces la primera vez."""
    import urllib.request
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    onnx = _MODEL_DIR / "kokoro-v1.0.onnx"
    voices = _MODEL_DIR / "voices-v1.0.bin"
    for f, url in [(onnx, f"{_MODEL_URL}/kokoro-v1.0.onnx"), (voices, f"{_MODEL_URL}/voices-v1.0.bin")]:
        if not f.exists():
            urllib.request.urlretrieve(url, f)
    return onnx, voices


@lru_cache(maxsize=1)
def _kokoro():
    from kokoro_onnx import Kokoro
    onnx, voices = _ensure_models()
    return Kokoro(str(onnx), str(voices))


def _lang_for(voice: str) -> str:
    """Kokoro nombra las voces por idioma en la 1ª letra (e=es, a/b=en)."""
    return "es" if voice[:1] == "e" else "en"


class KokoroVoiceProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def synthesize(self, text: str, out_path: Path, voice: str | None = None) -> Path:
        import soundfile as sf

        from ..secrets_store import get_secret
        v = (voice or get_secret("kokoro_voice") or self.settings.kokoro_voice or "em_alex").strip()
        v = _ALIAS.get(v.lower(), v)
        samples, sr = _kokoro().create(
            text, voice=v, speed=float(self.settings.kokoro_speed), lang=_lang_for(v))

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wav = out_path.with_suffix(".wav")
        sf.write(str(wav), samples, sr)
        if out_path.suffix.lower() == ".mp3":  # el pipeline espera narration.mp3
            run_ffmpeg(["-i", str(wav), str(out_path)])
            wav.unlink(missing_ok=True)
            return out_path
        return wav
