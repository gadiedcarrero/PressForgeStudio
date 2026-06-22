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

# Modelos imagen → video CON MOVIMIENTO; para escenas animadas / Skybot.
I2V_MODELS = {
    "kling-i2v": "fal-ai/kling-video/v2.1/standard/image-to-video",
    # Seedance (ByteDance): suele dar mejor movimiento/coherencia que Kling.
    "seedance": "fal-ai/bytedance/seedance/v1/pro/image-to-video",        # 1.0 Pro
    "seedance-lite": "fal-ai/bytedance/seedance/v1/lite/image-to-video",  # 1.0 Lite (más barato)
    "seedance2": "bytedance/seedance-2.0/image-to-video",                 # 2.0 (lo último)
}
DEFAULT_I2V = "kling-i2v"

# Modelos de LIP-SYNC: toman un VIDEO ya animado + audio y sincronizan la boca
# del rostro principal, dejando el resto del movimiento intacto (el otro personaje
# se sigue moviendo pero NO habla).
LIPSYNC_MODELS = {
    "latentsync": "fal-ai/latentsync",          # barato (~$0.2/40s)
    "sync2": "fal-ai/sync-lipsync/v2",          # premium (~$3/min)
}
DEFAULT_LIPSYNC = "latentsync"


def resolve_key() -> str:
    return get_secret("fal_api_key")


def _headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json",
            "Accept": "application/json"}


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _put(url: str, data: bytes, content_type: str) -> None:
    req = urllib.request.Request(url, data=data, method="PUT",
                                 headers={"Content-Type": content_type})
    try:
        urllib.request.urlopen(req, timeout=300)
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLError):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            urllib.request.urlopen(req, timeout=300, context=ctx)
        else:
            raise


def _upload(path: Path, key: str) -> str:
    """Sube un archivo al almacenamiento de fal y devuelve su URL pública.

    Algunos modelos (p. ej. OmniHuman) NO aceptan data URIs y exigen una URL
    descargable; subir es lo robusto para todos."""
    path = Path(path)
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    body = json.dumps({"content_type": mime, "file_name": path.name}).encode("utf-8")
    init = _req("https://rest.alpha.fal.ai/storage/upload/initiate?storage_type=fal-cdn-v3",
                key=key, data=body, method="POST")
    _put(init["upload_url"], path.read_bytes(), mime)
    return init["file_url"]


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
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    model_id = MODELS.get(model, MODELS[DEFAULT_MODEL])
    payload = {"image_url": _upload(image_path, key), "audio_url": _upload(audio_path, key)}
    if prompt:
        payload["prompt"] = prompt
    return _run_model(model_id, payload, out_path, poll_timeout=poll_timeout, on_event=on_event)


def image_to_video(image_path: Path, out_path: Path, *, prompt: str,
                   duration: str = "5", model: str = DEFAULT_I2V,
                   poll_timeout: int = 600, on_event=None) -> Path:
    """Anima una imagen (movimiento, sin audio) para una escena."""
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    model_id = I2V_MODELS.get(model, I2V_MODELS[DEFAULT_I2V])
    payload = {
        "image_url": _upload(image_path, key),
        "prompt": prompt or "subtle natural motion, cinematic camera, smooth",
        "duration": duration,
    }
    return _run_model(model_id, payload, out_path, poll_timeout=poll_timeout, on_event=on_event)


_VEO3_DIALOGUE = "fal-ai/veo3.1/fast/image-to-video"  # i2v con audio/diálogo nativo


def veo3_dialogue(image_path: Path, out_path: Path, *, prompt: str,
                  duration: str = "8s", audio: bool = True,
                  poll_timeout: int = 900, on_event=None) -> Path:
    """Veo 3.1 (fast) imagen→video. Con `audio=True` genera audio/voz nativos;
    con `audio=False` solo el VIDEO (mueve los labios con la línea del prompt, sin
    voz) para montar después una voz de ElevenLabs consistente encima."""
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    img_url = _upload(image_path, key)  # subir una sola vez, reusar en reintentos
    payload = {
        "image_url": img_url,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generate_audio": audio,
        "auto_fix": True,
        "negative_prompt": ("extra limbs, extra hands, duplicated hands, deformed hands, "
                            "distorted fingers, mutated anatomy, glitch, morphing, blurry"),
    }
    return _run_model(_VEO3_DIALOGUE, payload, out_path,
                      poll_timeout=poll_timeout, on_event=on_event)


_SEEDANCE2_I2V = "bytedance/seedance-2.0/image-to-video"  # i2v con audio + lip-sync


def seedance_dialogue(image_path: Path, out_path: Path, *, prompt: str,
                      duration: str = "8s", audio: bool = True,
                      poll_timeout: int = 900, on_event=None) -> Path:
    """Seedance 2.0 imagen→video con `generate_audio`: genera audio sincronizado
    incluyendo lip-synced speech (habla). Misma idea que veo3_dialogue."""
    import re as _re
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    dur = max(4, min(15, int(_re.sub(r"[^0-9]", "", str(duration)) or 8)))
    payload = {
        "image_url": _upload(image_path, key),
        "prompt": prompt,
        "duration": dur,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generate_audio": audio,
    }
    return _run_model(_SEEDANCE2_I2V, payload, out_path,
                      poll_timeout=poll_timeout, on_event=on_event)


_SEEDANCE2_REF = "bytedance/seedance-2.0/reference-to-video"  # consistencia por refs


def seedance_ref2video(image_paths: list, out_path: Path, *, prompt: str,
                       duration: str = "10s", audio: bool = True,
                       resolution: str = "720p", aspect_ratio: str = "9:16",
                       poll_timeout: int = 900, on_event=None) -> Path:
    """Seedance 2.0 reference-to-video: hasta 9 imágenes de referencia
    (personajes/naves) que se MANTIENEN consistentes. En el `prompt` se citan como
    @Image1, @Image2… `generate_audio` añade diálogo con lip-sync + música/efectos."""
    import re as _re
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    urls = [_upload(Path(p), key) for p in image_paths[:9] if p and Path(p).is_file()]
    if not urls:
        raise RuntimeError("Necesito al menos una imagen de referencia válida.")
    dur = max(4, min(15, int(_re.sub(r"[^0-9]", "", str(duration)) or 10)))
    payload = {
        "prompt": prompt,
        "image_urls": urls,
        "duration": dur,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "generate_audio": audio,
    }
    return _run_model(_SEEDANCE2_REF, payload, out_path,
                      poll_timeout=poll_timeout, on_event=on_event)


def lipsync(video_path: Path, audio_path: Path, out_path: Path, *,
            model: str = DEFAULT_LIPSYNC, poll_timeout: int = 600, on_event=None) -> Path:
    """Sincroniza la boca del rostro principal de un VIDEO ya animado con el audio
    dado (el resto del movimiento se conserva; los demás no 'hablan')."""
    key = resolve_key()
    if not key:
        raise RuntimeError("Falta la API key de fal.ai (Ajustes → API Keys).")
    model_id = LIPSYNC_MODELS.get(model, LIPSYNC_MODELS[DEFAULT_LIPSYNC])
    payload = {
        "video_url": _upload(video_path, key),
        "audio_url": _upload(audio_path, key),
        "loop_mode": "pingpong",
    }
    return _run_model(model_id, payload, out_path, poll_timeout=poll_timeout, on_event=on_event)
