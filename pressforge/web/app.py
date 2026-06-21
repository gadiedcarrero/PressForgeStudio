"""Web UI mínima (FastAPI) sobre el pipeline.

Single page: formulario para generar un reel, progreso en vivo y galería de los
reels ya producidos. Reutiliza `generate_reel` tal cual; cada generación corre
en un hilo aparte (la red + ffmpeg bloquean) y los eventos se guardan en memoria
para que el navegador los consulte por polling.

También expone una API JSON sencilla — la base que el dashboard Next.js (V3)
podrá consumir más adelante.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import auth, licensing
from ..config import music_path, output_path
from ..models import SourceFact, story_from_dict, story_to_dict
from ..pipeline import (
    auto_scene_count,
    duration_target_words,
    generate_stories,
    generate_story_from_fact,
    human_date,
    produce_reel,
)
from ..publishing import store as pubstore
from ..publishing.manual import caption_text
from ..publishing.scheduler import get_publisher, start_scheduler

_PLATFORMS = ["youtube", "instagram", "facebook", "tiktok"]

OUTPUT = output_path()  # carpeta raíz de reels (configurable vía STORAGE_DIR)
WEB_DIR = Path(__file__).parent
MUSIC_DIR = music_path()  # biblioteca de música (configurable vía STORAGE_DIR)
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
_MAX_MUSIC_BYTES = 50 * 1024 * 1024  # 50 MB

app = FastAPI(title="PressForge Studio")

# Estado en memoria (suficiente para uso local de 1 usuario).
_jobs: dict[str, dict] = {}        # render jobs en curso/terminados
_scripts: dict[str, dict] = {}     # guiones generados (editables antes de producir)
_candidates: dict[str, dict] = {}  # noticias/eventos encontrados (antes de gastar IA)
_lock = threading.Lock()


ASSETS_DIR = Path("assets")

OUTPUT.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT)), name="output")
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


start_scheduler()  # motor de publicación programada (hilo de fondo)

# Rutas accesibles SIN sesión (login/activación + assets públicos).
_PUBLIC = ("/login", "/api/login", "/api/setup", "/api/auth-status",
           "/api/license-status", "/api/activate", "/assets", "/favicon.ico")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    path = request.url.path
    if any(path == p or path.startswith(p + "/") or path == p for p in _PUBLIC) or path in _PUBLIC:
        return await call_next(request)
    if auth.valid_session(request.cookies.get("pf_session", "")):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"error": "no autenticado"}, status_code=401)
    return RedirectResponse("/login")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(WEB_DIR / "login.html")


@app.get("/api/auth-status")
def auth_status():
    return {"has_password": auth.has_password(), "licensed": licensing.is_licensed()}


@app.get("/api/license-status")
def license_status():
    return licensing.license_info()


@app.post("/api/activate")
def activate(payload: dict = Body(...)):
    if not licensing.activate(payload.get("key") or ""):
        return JSONResponse({"error": "Licencia inválida o expirada."}, status_code=400)
    return {"ok": True, **licensing.license_info()}


@app.post("/api/setup")
def setup(payload: dict = Body(...)):
    """Primer arranque: el usuario crea su contraseña (requiere licencia válida)."""
    if not licensing.is_licensed():
        return JSONResponse({"error": "Activa una licencia primero."}, status_code=403)
    if auth.has_password():
        return JSONResponse({"error": "Ya hay una contraseña configurada."}, status_code=400)
    pw = (payload.get("password") or "")
    if len(pw) < 4:
        return JSONResponse({"error": "La contraseña debe tener al menos 4 caracteres."}, status_code=400)
    auth.set_password(pw)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("pf_session", auth.new_session(), httponly=True, samesite="lax", max_age=14 * 24 * 3600)
    return resp


@app.post("/api/login")
def login(payload: dict = Body(...)):
    if not licensing.is_licensed():
        return JSONResponse({"error": "Activa una licencia primero."}, status_code=403)
    if not auth.verify_password(payload.get("password") or ""):
        return JSONResponse({"error": "Contraseña incorrecta."}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie("pf_session", auth.new_session(), httponly=True, samesite="lax", max_age=14 * 24 * 3600)
    return resp


@app.post("/api/logout")
def logout(request: Request):
    auth.end_session(request.cookies.get("pf_session", ""))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("pf_session")
    return resp


@app.get("/api/keys")
def get_keys():
    """Estado de las API keys (BYOK) — nunca devuelve el valor completo."""
    from ..providers._openai_client import resolve_openai_key
    from ..secrets_store import status

    st = status()
    # Si no está en la UI pero sí en el .env, indícalo (respaldo de desarrollo).
    oa = st.get("openai_api_key")
    if oa and not oa["set"] and resolve_openai_key():
        oa["env_fallback"] = True
    return {"keys": st}


@app.post("/api/keys")
def save_keys(payload: dict = Body(...)):
    """Guarda las API keys que el usuario escribe en Ajustes (solo si vienen)."""
    from ..secrets_store import KNOWN, set_secret, status

    for name in KNOWN:
        val = (payload.get(name) or "").strip()
        if val:  # vacío = no tocar (permite actualizar una sin reescribir otras)
            set_secret(name, val)
    return {"ok": True, "keys": status()}


_VOICE_PROVIDERS = ("openai", "elevenlabs", "kokoro")


@app.get("/api/image-config")
def get_image_config():
    from ..config import get_settings
    from ..providers.openai_image import STYLES, DEFAULT_STYLE
    from ..secrets_store import get_secret

    return {
        "style": get_secret("image_style") or DEFAULT_STYLE,
        "styles": list(STYLES.keys()),
        # providers por defecto del .env: arrancan los selectores de la UI bien.
        "provider": get_settings().image_provider,
        "script_provider": get_settings().script_provider,
        "subtitle_provider": get_settings().subtitle_provider,
    }


@app.post("/api/image-config")
def set_image_config(payload: dict = Body(...)):
    from ..providers.openai_image import STYLES
    from ..secrets_store import set_secret

    style = (payload.get("style") or "").strip()
    if style in STYLES:
        set_secret("image_style", style)
    return get_image_config()


@app.get("/api/voice-config")
def get_voice_config():
    from ..config import get_settings
    from ..providers.elevenlabs_voice import resolve_key as eleven_key
    from ..secrets_store import get_secret

    s = get_settings()
    return {
        "provider": get_secret("voice_provider") or s.voice_provider,
        "openai_voice": get_secret("openai_voice") or s.voice_name,
        "elevenlabs_voice_id": get_secret("elevenlabs_voice_id") or s.elevenlabs_voice_id,
        "elevenlabs_model": get_secret("elevenlabs_model") or s.elevenlabs_model,
        "elevenlabs_speed": get_secret("elevenlabs_speed") or "1.0",
        "elevenlabs_ready": bool(eleven_key()),
        "kokoro_voice": get_secret("kokoro_voice") or s.kokoro_voice,
    }


@app.get("/api/voice-preview/elevenlabs")
def voice_preview_elevenlabs(voice_id: str = ""):
    """Genera (y cachea) una muestra corta de una voz de ElevenLabs para escucharla."""
    from ..config import get_settings
    from ..providers.elevenlabs_voice import ElevenLabsVoiceProvider, resolve_key
    from ..secrets_store import get_secret

    if not resolve_key():
        return JSONResponse({"error": "Falta tu API key de ElevenLabs."}, status_code=400)
    if not voice_id:
        return JSONResponse({"error": "voice_id requerido"}, status_code=400)

    model = get_secret("elevenlabs_model") or get_settings().elevenlabs_model
    speed = get_secret("elevenlabs_speed") or "1.0"
    cache = Path("voice_previews")
    cache.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9_]", "", f"{voice_id}_{model}_{speed}")
    out = cache / f"{safe}.mp3"
    if not out.exists():
        try:
            ElevenLabsVoiceProvider().synthesize(
                "Hola. Esta es una muestra de mi voz para tus reels históricos.",
                out, voice=voice_id,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=400)
    return FileResponse(out, media_type="audio/mpeg")


@app.get("/api/voice-preview/kokoro")
def voice_preview_kokoro(voice: str = ""):
    """Genera (y cachea) una muestra de una voz LOCAL de Kokoro para escucharla."""
    from ..providers.kokoro_voice import KokoroVoiceProvider

    v = re.sub(r"[^a-zA-Z0-9_]", "", (voice or "em_alex").strip()) or "em_alex"
    cache = Path("voice_previews")
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"kokoro_{v}.mp3"
    if not out.exists():
        try:
            KokoroVoiceProvider().synthesize(
                "Hola. Esta es una muestra de mi voz para tus reels.", out, voice=v)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)
    return FileResponse(out, media_type="audio/mpeg")


@app.get("/api/voices/library")
def voices_library(language: str = "es", search: str = "", use_case: str = "", accent: str = "", page: int = 0):
    """Explorar la biblioteca de voces de ElevenLabs (requiere plan de pago para usarlas)."""
    from ..providers.elevenlabs_voice import library_voices, resolve_key

    if not resolve_key():
        return {"voices": [], "ready": False}
    try:
        res = library_voices(language=language, search=search, use_case=use_case, accent=accent, page=page)
        return {**res, "ready": True}
    except Exception as exc:  # noqa: BLE001
        return {"voices": [], "ready": True, "error": str(exc)}


@app.get("/api/voices/elevenlabs")
def elevenlabs_voices():
    from ..providers.elevenlabs_voice import list_voices, resolve_key

    if not resolve_key():
        return {"voices": [], "ready": False}
    try:
        return {"voices": list_voices(), "ready": True}
    except Exception as exc:  # noqa: BLE001
        return {"voices": [], "ready": True, "error": str(exc)}


@app.post("/api/voice-config")
def set_voice_config(payload: dict = Body(...)):
    from ..secrets_store import set_secret

    provider = (payload.get("provider") or "").strip()
    if provider in _VOICE_PROVIDERS:
        set_secret("voice_provider", provider)
    if (payload.get("openai_voice") or "").strip():
        set_secret("openai_voice", payload["openai_voice"].strip())
    if "elevenlabs_voice_id" in payload:
        set_secret("elevenlabs_voice_id", (payload.get("elevenlabs_voice_id") or "").strip())
    if (payload.get("elevenlabs_model") or "").strip():
        set_secret("elevenlabs_model", payload["elevenlabs_model"].strip())
    if (payload.get("elevenlabs_speed") or "").strip():
        set_secret("elevenlabs_speed", payload["elevenlabs_speed"].strip())
    if (payload.get("kokoro_voice") or "").strip():
        set_secret("kokoro_voice", payload["kokoro_voice"].strip())
    return get_voice_config()


@app.get("/favicon.ico")
def favicon():
    ico = ASSETS_DIR / "favicon.ico"
    return FileResponse(ico) if ico.exists() else JSONResponse({}, status_code=404)


# ─── Paso 1a (solo Histórico/Efemérides): buscar SIN gastar IA ───────────────
@app.post("/api/research")
def research(payload: dict = Body(...)):
    """Devuelve la lista de noticias/eventos reales encontrados, para que el
    usuario elija ANTES de gastar IA generando guiones."""
    from ..registry import get_research_provider

    mode = (payload.get("mode") or "").strip()
    niche = (payload.get("niche") or "").strip()
    try:
        if mode == "historic":
            if not niche:
                return JSONResponse({"error": "Escribe un tema a buscar."}, status_code=400)
            facts = get_research_provider().search(niche, limit=10)
            dates = ["" for _ in facts]
        elif mode == "onthisday":
            today = datetime.now()
            facts = get_research_provider().on_this_day(today.month, today.day, limit=60)
            dates = [human_date(today.day, today.month, f.year) for f in facts]
        elif mode == "reddit":
            from ..providers.reddit_research import RedditResearch
            facts = RedditResearch().curiosities(query=niche, limit=20)
            dates = ["" for _ in facts]
        else:
            return JSONResponse({"error": "Este modo no usa búsqueda."}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        src = "Reddit" if mode == "reddit" else "Wikipedia"
        return JSONResponse({"error": f"Error consultando {src}: {exc}"}, status_code=502)

    cands = []
    for f, date in zip(facts, dates):
        if not (f.title or f.extract):
            continue
        cid = uuid.uuid4().hex[:12]
        with _lock:
            _candidates[cid] = {
                "title": f.title, "extract": f.extract, "url": f.url,
                "year": f.year, "date": date,
            }
        snippet = f.extract.strip()
        if len(snippet) > 240:
            snippet = snippet[:240].rsplit(" ", 1)[0] + "…"
        cands.append({
            "id": cid, "title": f.title, "date": date, "year": f.year,
            "snippet": snippet, "url": f.url,
        })
    return {"candidates": cands}


# ─── Paso 1b: generar guion(es) para revisar/editar ──────────────────────────
@app.post("/api/scripts")
def create_scripts(payload: dict = Body(...)):
    mode = (payload.get("mode") or "invent").strip()
    raw_scenes = payload.get("scenes")
    scenes = max(3, min(18, int(raw_scenes))) if raw_scenes else None  # None = auto
    count = max(1, min(3, int(payload.get("count") or 1)))
    niche = (payload.get("niche") or "").strip() or None
    extra = (payload.get("extra") or "").strip() or None
    user_script = (payload.get("user_script") or "").strip() or None
    candidate_ids = payload.get("candidate_ids") or []
    duration = (payload.get("duration") or "medium").strip()
    combine = bool(payload.get("combine"))
    dialogue = bool(payload.get("dialogue"))
    script_provider = (payload.get("script_provider") or "").strip()  # 'ollama'/'openai'/'' (.env)
    # Libre: el guion del usuario manda el nº de escenas (auto), sin tope de 18.
    if duration == "free":
        scenes = None
    tw = duration_target_words(duration)
    # Idioma de salida: es / en / both → nombres para los prompts.
    _LMAP = {"es": "Spanish", "en": "English"}
    lang_in = (payload.get("language") or "es").strip()
    langs = ["Spanish", "English"] if lang_in == "both" else [_LMAP.get(lang_in, "Spanish")]

    # Camino con fuente (Histórico/Efemérides/Reddit): generar SOLO lo elegido.
    if candidate_ids:
        eff = scenes if scenes else auto_scene_count(mode="historic", expected_words=tw)
        cands = [_candidates.get(cid) for cid in candidate_ids[:6]]
        cands = [c for c in cands if c]
        if not cands:
            return JSONResponse({"error": "No encuentro lo seleccionado; vuelve a buscar."}, status_code=400)

        drafts = []
        # Combinar varias curiosidades en UN solo reel largo (por idioma).
        if combine and len(cands) > 1:
            merged = "\n\n".join(f"- {c['title']}: {c['extract']}" for c in cands)
            fact = SourceFact(title="Varias curiosidades", extract=merged,
                              url=cands[0].get("url", ""), year=None)
            for lang in langs:
                try:
                    story = generate_story_from_fact(fact, scenes=eff, extra=extra,
                                                     target_words=tw, language=lang,
                                                     script_provider=script_provider)
                except Exception as exc:  # noqa: BLE001
                    return JSONResponse({"error": str(exc)}, status_code=400)
                sid = uuid.uuid4().hex[:12]
                data = story_to_dict(story)
                with _lock:
                    _scripts[sid] = data
                drafts.append({"id": sid, **data})
            return {"scripts": drafts}

        for cand in cands:
            fact = SourceFact(
                title=cand["title"], extract=cand["extract"],
                url=cand["url"], year=cand.get("year"),
            )
            for lang in langs:
                try:
                    story = generate_story_from_fact(fact, scenes=eff, extra=extra,
                                                     target_words=tw, language=lang,
                                                     script_provider=script_provider)
                except Exception as exc:  # noqa: BLE001
                    return JSONResponse({"error": str(exc)}, status_code=400)
                story.source_date = cand.get("date", "")
                sid = uuid.uuid4().hex[:12]
                data = story_to_dict(story)
                with _lock:
                    _scripts[sid] = data
                drafts.append({"id": sid, **data})
        if not drafts:
            return JSONResponse({"error": "No pude generar guiones de lo seleccionado."}, status_code=400)
        return {"scripts": drafts}

    # Camino Inventar / Mi guion (una pasada por idioma).
    drafts = []
    for lang in langs:
        try:
            stories = generate_stories(
                mode=mode, niche=niche, scenes=scenes, extra=extra,
                user_script=user_script, count=count, duration=duration,
                dialogue=dialogue, language=lang, script_provider=script_provider,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=400)
        for story in stories:
            sid = uuid.uuid4().hex[:12]
            data = story_to_dict(story)
            with _lock:
                _scripts[sid] = data
            drafts.append({"id": sid, **data})
    return {"scripts": drafts}


@app.post("/api/scripts/{sid}")
def update_script(sid: str, payload: dict = Body(...)):
    """Guarda las ediciones del usuario sobre un guion."""
    with _lock:
        if sid not in _scripts:
            return JSONResponse({"error": "guion no encontrado"}, status_code=404)
        current = _scripts[sid]
    for key in ("title", "hook", "cta", "music_mood", "niche", "scenes"):
        if key in payload:
            current[key] = payload[key]
    with _lock:
        _scripts[sid] = current
    return {"id": sid, **current}


# ─── Paso 2: producir el reel desde un guion (ya editado) ─────────────────────
class _JobCancelled(BaseException):
    """Aborta un job en curso. Hereda de BaseException (no de Exception) para que
    los `except Exception` del pipeline NO la atrapen y la cancelación se propague."""


def _run_job(job_id: str, story_dict: dict, voice: str, music: str, brand_id: str,
             fmt: str = "still", presenter: str = "", video_model: str = "",
             image_provider: str = "", subtitle_provider: str = "") -> None:
    def on_event(msg: str) -> None:
        # Cada paso/iteración del pipeline pasa por aquí → es el punto de
        # cancelación: si el usuario pidió cancelar, abortamos en el acto.
        with _lock:
            if _jobs[job_id].get("cancel"):
                raise _JobCancelled()
            _jobs[job_id]["events"].append(msg)

    try:
        if fmt == "talking":
            from ..pipeline import produce_talking_reel
            result = produce_talking_reel(
                story_from_dict(story_dict),
                presenter=presenter or None,
                voice=voice or None,
                music=music or None,
                model=video_model or "kling-avatar",
                image_provider=image_provider or None,
                subtitle_provider=subtitle_provider or None,
                on_event=on_event,
            )
        elif fmt == "dialogue":
            from ..pipeline import produce_dialogue_reel
            result = produce_dialogue_reel(
                story_from_dict(story_dict),
                voice=voice or None,
                music=music or None,
                engine=video_model or "veo3",
                image_provider=image_provider or None,
                subtitle_provider=subtitle_provider or None,
                on_event=on_event,
            )
        elif fmt == "animated":
            result = produce_reel(
                story_from_dict(story_dict),
                voice=voice or None,
                music=music or None,
                animate=True,
                video_model=video_model or "kling-i2v",
                image_provider=image_provider or None,
                subtitle_provider=subtitle_provider or None,
                on_event=on_event,
            )
        else:
            result = produce_reel(
                story_from_dict(story_dict),
                voice=voice or None,
                music=music or None,
                image_provider=image_provider or None,
                subtitle_provider=subtitle_provider or None,
                on_event=on_event,
            )
        if brand_id:
            pubstore.set_reel_brand(result.workdir.name, brand_id)
        with _lock:
            _jobs[job_id].update(
                status="done",
                workdir=result.workdir.name,
                video=f"/output/{result.workdir.name}/reel.mp4",
                title=result.story.title,
                hook=result.story.hook,
                duration=round(result.duration, 1),
            )
    except _JobCancelled:
        with _lock:
            _jobs[job_id]["events"].append("✗ Cancelado por el usuario")
            _jobs[job_id].update(status="cancelled")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _jobs[job_id].update(status="error", error=str(exc))


@app.post("/api/produce")
def produce(payload: dict = Body(...)):
    sid = (payload.get("id") or "").strip()
    inline = payload.get("script")  # opcional: guion editado enviado directo
    with _lock:
        story_dict = inline or _scripts.get(sid)
    if not story_dict:
        return JSONResponse({"error": "guion no encontrado; genéralo primero"}, status_code=404)
    if sid and inline:  # persistir la última edición
        with _lock:
            _scripts[sid] = inline

    voice = (payload.get("voice") or "").strip()
    music = (payload.get("music") or "").strip()
    brand_id = (payload.get("brand_id") or "").strip()
    fmt = (payload.get("format") or "still").strip()
    presenter = (payload.get("presenter") or "").strip()
    video_model = (payload.get("video_model") or "").strip()
    image_provider = (payload.get("image_provider") or "").strip()  # 'local' / 'openai' / '' (default .env)
    subtitle_provider = (payload.get("subtitle_provider") or "").strip()  # 'whisper-local'/'whisper'/''
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running", "events": [], "title": story_dict.get("title", "")}
    threading.Thread(
        target=_run_job,
        args=(job_id, dict(story_dict), voice, music, brand_id, fmt, presenter, video_model,
              image_provider, subtitle_provider),
        daemon=True,
    ).start()
    return {"job_id": job_id}


def _library():
    from ..music_library import MusicLibrary

    return MusicLibrary()


@app.get("/api/music")
def list_music():
    """Pistas con sus tags (para el selector y el gestor)."""
    return {"tracks": _library().entries()}


_IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@app.post("/api/reference/upload")
async def upload_reference(file: UploadFile = File(...)):
    """Sube una imagen de referencia para una escena (se recreará en el estilo)."""
    from ..config import data_path

    ext = Path(file.filename or "").suffix.lower()
    if ext not in _IMG_EXTS:
        return JSONResponse({"error": f"formato no soportado ({ext or '?'}). Usa PNG/JPG/WEBP."},
                            status_code=400)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        return JSONResponse({"error": "imagen demasiado grande (máx 15 MB)."}, status_code=400)
    refs = data_path() / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex + ext
    (refs / name).write_bytes(data)
    return {"id": name, "url": f"/reference/{name}"}


@app.get("/reference/{name}")
def reference_file(name: str):
    from ..config import data_path

    safe = Path(name).name  # anti path-traversal
    path = data_path() / "refs" / safe
    if not path.is_file():
        return JSONResponse({"error": "no encontrado"}, status_code=404)
    return FileResponse(path)


@app.post("/api/music/upload")
async def upload_music(file: UploadFile = File(...), tags: str = Form("")):
    name = Path(file.filename or "").name  # evita path traversal
    ext = Path(name).suffix.lower()
    if not name or ext not in _AUDIO_EXTS:
        return JSONResponse(
            {"error": f"formato no soportado ({ext or '?'}). Usa: {', '.join(sorted(_AUDIO_EXTS))}"},
            status_code=400,
        )
    data = await file.read()
    if len(data) > _MAX_MUSIC_BYTES:
        return JSONResponse({"error": "archivo demasiado grande (máx 50 MB)."}, status_code=400)

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    (MUSIC_DIR / name).write_bytes(data)

    lib = _library()
    tag_list = [t.strip() for t in tags.replace(",", " ").split() if t.strip()]
    if tag_list:
        lib.set_tags(name, tag_list)
    return {"saved": name, "tracks": lib.entries()}


@app.post("/api/music/tags")
def set_music_tags(payload: dict = Body(...)):
    name = Path(payload.get("name") or "").name
    if not name:
        return JSONResponse({"error": "falta el nombre de la pista"}, status_code=400)
    raw = payload.get("tags", [])
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    lib = _library()
    lib.set_tags(name, [str(t) for t in raw])
    return {"ok": True, "tracks": lib.entries()}


@app.post("/api/music/delete")
def delete_music(payload: dict = Body(...)):
    name = Path(payload.get("name") or "").name
    if not name:
        return JSONResponse({"error": "falta el nombre de la pista"}, status_code=400)
    lib = _library()
    lib.delete(name)
    return {"ok": True, "tracks": lib.entries()}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job no encontrado"}, status_code=404)
        return dict(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Marca un job para cancelar. El proceso aborta al terminar el paso actual
    (la cancelación se hace efectiva en el siguiente checkpoint del pipeline)."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return JSONResponse({"error": "job no encontrado"}, status_code=404)
        if job.get("status") == "running":
            job["cancel"] = True
            job["events"].append("⏹ Cancelando… (terminando el paso en curso)")
        return {"status": job.get("status"), "cancelling": bool(job.get("cancel"))}


# ─── Skybot (sección privada): nave → imagen + 2 videos con plantilla fija ───
def _run_skybot(job_id: str, description: str, opts: dict) -> None:
    def on_event(msg: str) -> None:
        with _lock:
            if _jobs[job_id].get("cancel"):
                raise _JobCancelled()
            _jobs[job_id]["events"].append(msg)

    try:
        from ..skybot import produce_skybot
        result = produce_skybot(description, on_event=on_event, **opts)
        with _lock:
            _jobs[job_id].update(status="done", **result)
    except _JobCancelled:
        with _lock:
            _jobs[job_id]["events"].append("✗ Cancelado por el usuario")
            _jobs[job_id].update(status="cancelled")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _jobs[job_id].update(status="error", error=str(exc))


@app.post("/api/skybot")
def skybot_generate(payload: dict = Body(...)):
    desc = (payload.get("description") or "").strip()
    if not desc:
        return JSONResponse({"error": "Describe la nave primero."}, status_code=400)
    # La referencia debe ser un archivo dentro de la carpeta de refs (seguridad).
    ref = (payload.get("reference") or "").strip()
    if ref:
        from ..config import output_path as _op
        refs_dir = (_op() / "skybot" / "_refs").resolve()
        try:
            if refs_dir not in Path(ref).resolve().parents:
                ref = ""
        except Exception:  # noqa: BLE001
            ref = ""
    opts = {
        "name": (payload.get("name") or "").strip(),
        "narration_es": (payload.get("narration_es") or "").strip(),
        "narration_en": (payload.get("narration_en") or "").strip(),
        "voice_es": (payload.get("voice_es") or "").strip(),
        "voice_en": (payload.get("voice_en") or "").strip(),
        "music": (payload.get("music") or "").strip(),
        "image_engine": (payload.get("image_engine") or "local").strip(),
        "video_engine": (payload.get("video_engine") or "local").strip(),
        "reference": ref,
    }
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running", "events": [], "title": "Skybot"}
    threading.Thread(target=_run_skybot, args=(job_id, desc, opts), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/skybot")
def skybot_list():
    from ..skybot import list_skybot
    return {"ships": list_skybot()}


@app.post("/api/skybot/upload")
async def skybot_upload(image: UploadFile = File(...)):
    """Sube la imagen de referencia de la nave (ancla la consistencia)."""
    refs = output_path() / "skybot" / "_refs"
    refs.mkdir(parents=True, exist_ok=True)
    ext = (Path(image.filename or "ref.png").suffix or ".png").lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        return JSONResponse({"error": "Usa PNG, JPG o WEBP."}, status_code=400)
    dest = refs / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(await image.read())
    return {"reference": str(dest), "url": f"/output/skybot/_refs/{dest.name}"}


@app.get("/api/voice-sample/{voice}")
def voice_sample(voice: str):
    """Muestra de audio de una voz (se genera la primera vez que se pide)."""
    from ..voice_samples import VOICES, ensure_sample

    if voice not in VOICES:
        return JSONResponse({"error": "voz desconocida"}, status_code=404)
    try:
        path = ensure_sample(voice)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/api/reels")
def list_reels():
    queue = pubstore.list_queue()
    sched_count: dict[str, int] = {}
    for it in queue:
        if it.get("status") == "pending":
            sched_count[it.get("reel_id", "")] = sched_count.get(it.get("reel_id", ""), 0) + 1

    reels = []
    if OUTPUT.exists():
        for d in sorted(OUTPUT.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            mp4, sj = d / "reel.mp4", d / "story.json"
            if not sj.exists():
                continue
            done = mp4.exists()
            # Incompleto pero RECUPERABLE: media lista (voz + subs), falta montar.
            resumable = (not done) and (d / "narration.mp3").exists() and (d / "subs.ass").exists()
            if not done and not resumable:
                continue
            try:
                data = json.loads(sj.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}
            imgs = sorted((d / "images").glob("*.png")) if (d / "images").exists() else []
            reels.append(
                {
                    "id": d.name,
                    "title": data.get("title") or d.name,
                    "niche": data.get("niche", ""),
                    "hook": data.get("hook", ""),
                    "duration": data.get("duration_s"),
                    "video": f"/output/{d.name}/reel.mp4" if done else None,
                    "thumb": f"/output/{d.name}/images/{imgs[0].name}" if imgs else None,
                    "incomplete": not done,
                    "has_post": bool(pubstore.get_post(d.name)),
                    "scheduled": sched_count.get(d.name, 0),
                    "brand_id": pubstore.get_reel_brand(d.name),
                    "brand_name": pubstore.get_brand(pubstore.get_reel_brand(d.name)).get("name", ""),
                }
            )
    return reels


@app.post("/api/reels/{reel_id}/resume")
def resume_reel(reel_id: str):
    """Rehace SOLO el montaje final de un reel cuya media ya está generada."""
    from ..pipeline import resume_render

    wd = OUTPUT / Path(reel_id).name
    if not (wd / "story.json").exists():
        return JSONResponse({"error": "reel no encontrado"}, status_code=404)
    if (wd / "reel.mp4").exists():
        return JSONResponse({"error": "este reel ya está montado"}, status_code=400)

    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running", "events": ["Reanudando montaje…"], "title": reel_id}

    def _run():
        try:
            resume_render(wd)
            with _lock:
                _jobs[job_id]["events"].append("✓ Montaje listo")
                _jobs[job_id].update(status="done", workdir=wd.name,
                                     video=f"/output/{wd.name}/reel.mp4")
        except Exception as exc:  # noqa: BLE001
            with _lock:
                _jobs[job_id].update(status="error", error=str(exc))

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


# ─── Editor de post (caption / hashtags / plataformas) ───────────────────────
def _suggest_post(reel_id: str) -> dict:
    """Caption + hashtags sugeridos a partir del guion (sin IA, editable)."""
    sj = OUTPUT / reel_id / "story.json"
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        data = {}
    hook = (data.get("hook") or "").strip()
    cta = (data.get("cta") or "").strip()
    src = (data.get("source_url") or "").strip()
    caption = hook
    if cta:
        caption += "\n\n" + cta
    if src:
        caption += f"\n\nFuente: {src}"
    base_tags = ["historia", "curiosidades", "shorts", "reels", "viral"]
    niche_tags = [w.lower() for w in (data.get("niche", "") or "").split() if len(w) > 3][:3]
    brand = pubstore.get_brand(pubstore.get_reel_brand(reel_id))
    brand_tags = [str(t).lstrip("#") for t in (brand.get("hashtags") or [])]
    seen, hashtags = set(), []
    for t in brand_tags + niche_tags + base_tags:
        if t and t not in seen:
            seen.add(t)
            hashtags.append(t)
    platforms = list((brand.get("channels") or {}).keys())
    return {"caption": caption.strip(), "hashtags": hashtags, "platforms": platforms,
            "brand_id": brand.get("id", "")}


def _safe_filename(name: str, default: str = "reel") -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "", (name or "")).strip()
    name = re.sub(r"\s+", " ", name) or default
    return name[:80] + ".mp4"


@app.get("/api/reels/{reel_id}/download")
def download_reel(reel_id: str):
    mp4 = OUTPUT / reel_id / "reel.mp4"
    if not mp4.exists():
        return JSONResponse({"error": "reel no encontrado"}, status_code=404)
    title = reel_id
    try:
        title = json.loads((OUTPUT / reel_id / "story.json").read_text(encoding="utf-8")).get("title") or reel_id
    except Exception:  # noqa: BLE001
        pass
    return FileResponse(mp4, media_type="video/mp4", filename=_safe_filename(title))


@app.get("/api/reels/{reel_id}/post")
def get_post(reel_id: str):
    saved = pubstore.get_post(reel_id)
    if saved:
        return saved
    return _suggest_post(reel_id)


@app.post("/api/reels/{reel_id}/post")
def save_post(reel_id: str, payload: dict = Body(...)):
    if not (OUTPUT / reel_id / "reel.mp4").exists():
        return JSONResponse({"error": "reel no encontrado"}, status_code=404)
    caption = (payload.get("caption") or "").strip()
    raw_tags = payload.get("hashtags", [])
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.replace(",", " ").split()
    hashtags = [str(t).lstrip("#").strip() for t in raw_tags if str(t).strip()]
    platforms = [p for p in (payload.get("platforms") or []) if p in _PLATFORMS]
    brand_id = payload.get("brand_id")
    return pubstore.set_post(reel_id, caption=caption, hashtags=hashtags,
                             platforms=platforms, brand_id=brand_id)


def _reel_story(reel_id: str) -> dict:
    try:
        return json.loads((OUTPUT / reel_id / "story.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ─── Descripción IA + reels relacionados (internal linking) ──────────────────
@app.post("/api/reels/{reel_id}/describe")
def describe_reel(reel_id: str):
    from ..registry import get_script_provider

    data = _reel_story(reel_id)
    if not data:
        return JSONResponse({"error": "reel no encontrado"}, status_code=404)
    title = data.get("title", "")
    narration = data.get("full_narration") or " ".join(
        s.get("narration", "") for s in data.get("scenes", [])
    )
    try:
        desc = get_script_provider().describe(title=title, narration=narration)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)

    cur = pubstore.get_post(reel_id)
    pubstore.set_post(
        reel_id, caption=desc["caption"], hashtags=desc["hashtags"],
        platforms=cur.get("platforms", []), brand_id=cur.get("brand_id"),
        entities=desc["entities"],
    )
    return desc


@app.get("/api/reels/{reel_id}/related")
def related_reels(reel_id: str):
    """Otros reels que mencionan las mismas entidades (para enlazarlos)."""
    ents = [e.lower() for e in pubstore.get_post(reel_id).get("entities", []) if e.strip()]
    if not ents:
        return {"related": [], "needs_describe": True}

    out = []
    for d in sorted(OUTPUT.iterdir(), reverse=True):
        if not d.is_dir() or d.name == reel_id:
            continue
        if not ((d / "reel.mp4").exists() and (d / "story.json").exists()):
            continue
        data = _reel_story(d.name)
        haystack = " ".join([
            data.get("title", ""), data.get("hook", ""),
            data.get("full_narration", ""), data.get("niche", ""),
        ]).lower()
        matched = sorted({e for e in ents if e in haystack})
        if matched:
            imgs = sorted((d / "images").glob("*.png")) if (d / "images").exists() else []
            out.append({
                "id": d.name,
                "title": data.get("title") or d.name,
                "video": f"/output/{d.name}/reel.mp4",
                "thumb": f"/output/{d.name}/images/{imgs[0].name}" if imgs else None,
                "matched": matched,
            })
    return {"related": out, "needs_describe": False}


# ─── Programación ────────────────────────────────────────────────────────────
@app.post("/api/schedule")
def schedule(payload: dict = Body(...)):
    """Programa uno o varios reels. Ej: 5 reels, empezando el día X a las HH:MM,
    uno cada `interval_days`, en las plataformas dadas."""
    reel_ids = [r for r in (payload.get("reel_ids") or []) if (OUTPUT / r / "reel.mp4").exists()]
    if not reel_ids:
        return JSONResponse({"error": "Selecciona al menos un reel válido."}, status_code=400)
    platforms = [p for p in (payload.get("platforms") or []) if p in _PLATFORMS]
    if not platforms:
        return JSONResponse({"error": "Elige al menos una plataforma."}, status_code=400)

    start = (payload.get("start") or "").strip()  # 'YYYY-MM-DDTHH:MM'
    try:
        base = datetime.fromisoformat(start)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "Fecha/hora de inicio inválida."}, status_code=400)
    interval_days = max(0, int(payload.get("interval_days") or 1))

    items = []
    for i, reel_id in enumerate(reel_ids):
        when = base + timedelta(days=interval_days * i)
        for platform in platforms:
            items.append({
                "reel_id": reel_id,
                "platform": platform,
                "scheduled_at": when.isoformat(timespec="minutes"),
            })
    created = pubstore.add_queue_items(items)
    return {"created": len(created), "queue": _queue_view()}


def _queue_view() -> list[dict]:
    out = []
    for it in pubstore.list_queue():
        rid = it.get("reel_id", "")
        sj = OUTPUT / rid / "story.json"
        title = rid
        try:
            title = json.loads(sj.read_text(encoding="utf-8")).get("title") or rid
        except Exception:  # noqa: BLE001
            pass
        out.append({**it, "title": title, "video": f"/output/{rid}/reel.mp4"})
    return out


@app.get("/api/schedule")
def list_schedule():
    return {"queue": _queue_view()}


@app.post("/api/schedule/cancel")
def cancel_schedule(payload: dict = Body(...)):
    qid = (payload.get("id") or "").strip()
    pubstore.remove_queue(qid)
    return {"ok": True, "queue": _queue_view()}


# ─── Publicar ahora (manual asistido) ────────────────────────────────────────
@app.post("/api/publish")
def publish_now(payload: dict = Body(...)):
    reel_id = (payload.get("reel_id") or "").strip()
    reel_path = OUTPUT / reel_id / "reel.mp4"
    if not reel_path.exists():
        return JSONResponse({"error": "reel no encontrado"}, status_code=404)
    post = pubstore.get_post(reel_id) or _suggest_post(reel_id)
    platforms = [p for p in (payload.get("platforms") or post.get("platforms") or []) if p in _PLATFORMS]
    if not platforms:
        return JSONResponse({"error": "Elige al menos una plataforma."}, status_code=400)

    results = []
    for platform in platforms:
        res = get_publisher(platform).publish(
            reel_path=reel_path,
            caption=post.get("caption", ""),
            hashtags=post.get("hashtags", []),
            platform=platform,
            channel=pubstore.channels_for_reel(reel_id, platform),
        )
        results.append({"platform": platform, "status": res.status, "detail": res.detail, "url": res.url})
    # Texto listo para copiar/pegar
    text = caption_text(post.get("caption", ""), post.get("hashtags", []))
    return {"results": results, "caption_text": text, "video": f"/output/{reel_id}/reel.mp4"}


# ─── Marcas / canales por nicho ──────────────────────────────────────────────
@app.get("/api/brands")
def list_brands():
    return {"brands": pubstore.list_brands(), "platforms": _PLATFORMS}


@app.post("/api/brands")
def save_brand(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "La marca necesita un nombre."}, status_code=400)
    raw_tags = payload.get("hashtags", [])
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.replace(",", " ").split()
    channels = payload.get("channels") or {}
    clean_ch = {p: channels[p] for p in channels if p in _PLATFORMS and isinstance(channels[p], dict)}
    brand = pubstore.upsert_brand({
        "id": (payload.get("id") or "").strip() or None,
        "name": name,
        "niche": (payload.get("niche") or "").strip(),
        "description": (payload.get("description") or "").strip(),
        "hashtags": [str(t).lstrip("#").strip() for t in raw_tags if str(t).strip()],
        "voice": (payload.get("voice") or "").strip(),
        "music": (payload.get("music") or "").strip(),
        # plan: etiqueta de estrategia (ej. "A" para el plan de CPM alto); language: idioma por defecto del guion/voz
        "plan": (payload.get("plan") or "").strip(),
        "language": (payload.get("language") or "").strip(),
        "channels": clean_ch,
    })
    return {"brand": brand, "brands": pubstore.list_brands()}


@app.post("/api/brands/delete")
def remove_brand(payload: dict = Body(...)):
    pubstore.delete_brand((payload.get("id") or "").strip())
    return {"brands": pubstore.list_brands()}


@app.get("/api/brands/branding")
def brand_branding_existing(name: str = ""):
    """Todas las generaciones (intentos) de brand kit de una marca, en Drive."""
    from ..branding import list_kits

    if not name.strip():
        return {"kits": []}
    return list_kits(name.strip())


@app.get("/branding/{slug}/{attempt}/{filename}")
def branding_file(slug: str, attempt: str, filename: str):
    """Sirve una pieza del brand kit desde STORAGE_DIR/branding (Drive)."""
    from ..config import branding_path

    # saneo anti path-traversal: solo nombres simples.
    for part in (slug, attempt, filename):
        if "/" in part or "\\" in part or ".." in part:
            return JSONResponse({"error": "ruta inválida"}, status_code=400)
    path = branding_path() / slug / attempt / filename
    if not path.is_file():
        return JSONResponse({"error": "no encontrado"}, status_code=404)
    return FileResponse(path, media_type="image/png")


@app.post("/api/brands/branding")
def brand_branding(payload: dict = Body(...)):
    """Genera logo(s) + banners por red para una marca (Brand Kit con IA)."""
    from ..branding import generate_brand_kit

    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "Escribe el nombre de la marca primero."}, status_code=400)
    niche = (payload.get("niche") or "").strip()
    style = (payload.get("style") or "").strip()
    try:
        return generate_brand_kit(name, niche, style)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
