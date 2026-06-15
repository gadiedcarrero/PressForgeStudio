"""VoiceProvider con ElevenLabs (voz premium, muy natural en español).

Usa la API REST de Text-to-Speech. La API key se resuelve igual que OpenAI:
Ajustes → API Keys (BYOK) primero, luego `.env` (ELEVENLABS_API_KEY).

Se activa con VOICE_PROVIDER=elevenlabs. La voz se elige con ELEVENLABS_VOICE_ID
(coge un voice_id de tu panel → Voces). El modelo por defecto es
`eleven_multilingual_v2` (buen español).
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from ..config import get_settings
from ..secrets_store import get_secret

_API = "https://api.elevenlabs.io/v1/text-to-speech"


def resolve_key() -> str:
    return get_secret("elevenlabs_api_key") or get_settings().elevenlabs_api_key


class ElevenLabsVoiceProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def synthesize(self, text: str, out_path: Path, voice: str | None = None) -> Path:
        key = resolve_key()
        if not key:
            raise RuntimeError("Falta la API key de ElevenLabs (Ajustes → API Keys).")
        # `voice` del selector son nombres de OpenAI (onyx…), no sirven aquí:
        # usamos un voice_id explícito solo si parece uno (largo), si no el de config.
        voice_id = voice if (voice and len(voice) >= 15) else self.settings.elevenlabs_voice_id

        out_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_API}/{voice_id}?output_format=mp3_44100_128"
        body = json.dumps({"text": text, "model_id": self.settings.elevenlabs_model}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        )
        try:
            self._download(req, out_path)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"ElevenLabs error {exc.code}: {detail}")
        return out_path

    def _download(self, req: urllib.request.Request, out_path: Path) -> None:
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                out_path.write_bytes(resp.read())
        except urllib.error.URLError as exc:
            # Fallback solo si falla la verificación TLS (reloj del sistema desfasado).
            if isinstance(getattr(exc, "reason", None), ssl.SSLError):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                    out_path.write_bytes(resp.read())
            else:
                raise
