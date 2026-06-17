"""Proveedor de video IA vía fal.ai (personaje 3D que habla / se mueve).

Convierte una imagen de personaje + un audio (la voz de ElevenLabs/OpenAI) en un
clip de video con lip-sync, usando modelos de fal (Kling AI Avatar, OmniHuman…).

API REST de cola de fal:
  POST https://queue.fal.run/{model}          -> {request_id, status_url, response_url}
  GET  .../requests/{id}/status               -> {status: IN_QUEUE|IN_PROGRESS|COMPLETED}
  GET  .../requests/{id}                       -> resultado (video.url)

Key BYOK: Ajustes → API Keys (`fal_api_key`). Las imágenes/audio se mandan como
data URI (base64) para no depender de la subida a su almacenamiento.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..secrets_store import get_secret

_QUEUE = "https://queue.fal.run"

# Modelos imagen+audio → video hablando (lip-sync).
MODELS = {
    "kling-avatar": "fal-ai/kling-video/ai-avatar/v2/standard",  # ~$0.056/s, equilibrado
    "omnihuman": "fal-ai/bytedance/omnihuman",                   # ~$0.14/s, más gesto/cuerpo
}
DEFAULT_MODEL = "kling-avatar"

# Modelos imagen → video CON MOVIMIENTO (sin audio); para escenas animadas.
I2V_MODELS = {
    "kling-i2v": "fal-ai/kling-video/v2.1/standard/image-to-video",
}
DEFAULT_I2V = "kling-i2v"


def resolve_key() -> str:
    return get_secret("fal_api_key")


def _headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json",
            "Accept": "application/json"}


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _req(url: str, *, key: str, data: bytes | None = None, method: str = "GET") -> dict:
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:  # fallback TLS (reloj desfasado)
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        raise


def _run_model(model_id: str, payload: dict, out_path: Path, *,
               poll_timeout: int = 600, on_event=None) -> Path:
    """Encola un modelo de fal, espera y descarga el video resultante."""
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")

    submit = _req(f"{_QUEUE}/{model_id}", key=key,
                  data=json.dumps(payload).encode("utf-8"), method="POST")
    # Usar las URLs que fal devuelve (la ruta de requests difiere en modelos anidados).
    status_url = submit.get("status_url")
    response_url = submit.get("response_url")
    if not status_url or not response_url:
        raise RuntimeError(f"fal no devolvió status_url/response_url: {submit}")

    waited = 0
    while waited < poll_timeout:
        st = _req(status_url, key=key).get("status")
        if st == "COMPLETED":
            break
        if st in (None, "FAILED", "ERROR"):
            raise RuntimeError(f"fal falló (status={st}).")
        if on_event:
            on_event(f"    · render en fal… ({st})")
        time.sleep(5)
        waited += 5
    else:
        raise RuntimeError("fal: tiempo de espera agotado generando el video.")

    result = _req(response_url, key=key)
    video_url = (result.get("video") or {}).get("url")
    if not video_url:
        raise RuntimeError(f"fal no devolvió video: {result}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(video_url, timeout=300) as resp:
        out_path.write_bytes(resp.read())
    return out_path


def talking_avatar(image_path: Path, audio_path: Path, out_path: Path, *,
                   model: str = DEFAULT_MODEL, prompt: str = "",
                   poll_timeout: int = 600, on_event=None) -> Path:
    """Genera un video del personaje (imagen) hablando con el audio dado (lip-sync)."""
    model_id = MODELS.get(model, MODELS[DEFAULT_MODEL])
    payload = {"image_url": _data_uri(image_path), "audio_url": _data_uri(audio_path)}
    if prompt:
        payload["prompt"] = prompt
    return _run_model(model_id, payload, out_path, poll_timeout=poll_timeout, on_event=on_event)


def image_to_video(image_path: Path, out_path: Path, *, prompt: str,
                   duration: str = "5", model: str = DEFAULT_I2V,
                   poll_timeout: int = 600, on_event=None) -> Path:
    """Anima una imagen (movimiento, sin audio) para una escena."""
    model_id = I2V_MODELS.get(model, I2V_MODELS[DEFAULT_I2V])
    payload = {
        "image_url": _data_uri(image_path),
        "prompt": prompt or "subtle natural motion, cinematic camera, smooth",
        "duration": duration,
    }
    return _run_model(model_id, payload, out_path, poll_timeout=poll_timeout, on_event=on_event)
