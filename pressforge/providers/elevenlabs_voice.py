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
import urllib.parse
import urllib.request
from pathlib import Path

from ..config import get_settings
from ..secrets_store import get_secret

_API = "https://api.elevenlabs.io/v1/text-to-speech"


def resolve_key() -> str:
    return get_secret("elevenlabs_api_key") or get_settings().elevenlabs_api_key


def _urlopen(req):
    """urlopen con fallback TLS (reloj del sistema desfasado)."""
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return urllib.request.urlopen(req, timeout=60, context=ctx)
        raise


def list_voices() -> list[dict]:
    """Lista las voces de la cuenta de ElevenLabs: [{id, name}]. Vacío si no hay key."""
    key = resolve_key()
    if not key:
        return []
    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": key, "Accept": "application/json"},
    )
    with _urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [{"id": v.get("voice_id", ""), "name": v.get("name", "")}
            for v in data.get("voices", []) if v.get("voice_id")]


def library_voices(*, language: str = "es", search: str = "", use_case: str = "",
                   accent: str = "", page: int = 0, page_size: int = 30) -> dict:
    """Explora la biblioteca pública de voces de ElevenLabs con filtros.
    Devuelve {voices:[{id,name,accent,gender,use_case,category,preview,description}], has_more}."""
    key = resolve_key()
    if not key:
        return {"voices": [], "has_more": False}
    params = {"page_size": page_size, "page": page}
    if language: params["language"] = language
    if search: params["search"] = search
    if use_case: params["use_cases"] = use_case
    if accent: params["accent"] = accent
    url = "https://api.elevenlabs.io/v1/shared-voices?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"xi-api-key": key, "Accept": "application/json"})
    with _urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    voices = [{
        "id": v.get("voice_id", ""), "name": v.get("name", ""),
        "accent": v.get("accent", ""), "gender": v.get("gender", ""),
        "use_case": v.get("use_case", ""), "category": v.get("category", ""),
        "preview": v.get("preview_url", ""), "description": v.get("descriptive", ""),
    } for v in data.get("voices", []) if v.get("voice_id")]
    return {"voices": voices, "has_more": bool(data.get("has_more"))}


class ElevenLabsVoiceProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    def synthesize(self, text: str, out_path: Path, voice: str | None = None) -> Path:
        key = resolve_key()
        if not key:
            raise RuntimeError("Falta la API key de ElevenLabs (Ajustes → API Keys).")
        # voice_id explícito (largo) → el elegido en Ajustes → el de .env.
        voice_id = (voice if (voice and len(voice) >= 15) else None) \
            or get_secret("elevenlabs_voice_id") or self.settings.elevenlabs_voice_id

        model = get_secret("elevenlabs_model") or self.settings.elevenlabs_model

        # Velocidad (0.7 lenta … 1.2 rápida). Las voces "cinematic" tienden a ir
        # lentas y con pausas dramáticas; subir speed acorta esas pausas.
        try:
            speed = float(get_secret("elevenlabs_speed") or "1.0")
        except ValueError:
            speed = 1.0
        speed = max(0.7, min(1.2, speed))
        voice_settings = {
            "stability": 0.5, "similarity_boost": 0.75,
            "style": 0.0, "use_speaker_boost": True, "speed": speed,
        }

        out_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{_API}/{voice_id}?output_format=mp3_44100_128"
        body = json.dumps({"text": text, "model_id": model,
                           "voice_settings": voice_settings}).encode("utf-8")
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
