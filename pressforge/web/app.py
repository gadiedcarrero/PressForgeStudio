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

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import output_path
from ..models import SourceFact, story_from_dict, story_to_dict
from ..pipeline import (
    auto_scene_count,
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
MUSIC_DIR = Path("assets/music")
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


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


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
    rp = get_research_provider()
    try:
        if mode == "historic":
            if not niche:
                return JSONResponse({"error": "Escribe un tema a buscar."}, status_code=400)
            facts = rp.search(niche, limit=10)
            dates = ["" for _ in facts]
        elif mode == "onthisday":
            today = datetime.now()
            facts = rp.on_this_day(today.month, today.day, limit=60)
            dates = [human_date(today.day, today.month, f.year) for f in facts]
        else:
            return JSONResponse({"error": "Este modo no usa búsqueda."}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Error consultando Wikipedia: {exc}"}, status_code=502)

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

    # Camino Histórico/Efemérides: generar SOLO de lo que el usuario eligió.
    if candidate_ids:
        eff = scenes if scenes else auto_scene_count(mode="historic")
        drafts = []
        for cid in candidate_ids[:6]:
            with _lock:
                cand = _candidates.get(cid)
            if not cand:
                continue
            fact = SourceFact(
                title=cand["title"], extract=cand["extract"],
                url=cand["url"], year=cand.get("year"),
            )
            try:
                story = generate_story_from_fact(fact, scenes=eff, extra=extra)
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

    # Camino Inventar / Mi guion.
    try:
        stories = generate_stories(
            mode=mode,
            niche=niche,
            scenes=scenes,
            extra=extra,
            user_script=user_script,
            count=count,
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)

    drafts = []
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
def _run_job(job_id: str, story_dict: dict, voice: str, music: str, brand_id: str) -> None:
    def on_event(msg: str) -> None:
        with _lock:
            _jobs[job_id]["events"].append(msg)

    try:
        result = produce_reel(
            story_from_dict(story_dict),
            voice=voice or None,
            music=music or None,
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
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running", "events": [], "title": story_dict.get("title", "")}
    threading.Thread(
        target=_run_job, args=(job_id, dict(story_dict), voice, music, brand_id), daemon=True
    ).start()
    return {"job_id": job_id}


def _library():
    from ..music_library import MusicLibrary

    return MusicLibrary()


@app.get("/api/music")
def list_music():
    """Pistas con sus tags (para el selector y el gestor)."""
    return {"tracks": _library().entries()}


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
            if not (mp4.exists() and sj.exists()):
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
                    "video": f"/output/{d.name}/reel.mp4",
                    "thumb": f"/output/{d.name}/images/{imgs[0].name}" if imgs else None,
                    "has_post": bool(pubstore.get_post(d.name)),
                    "scheduled": sched_count.get(d.name, 0),
                    "brand_id": pubstore.get_reel_brand(d.name),
                    "brand_name": pubstore.get_brand(pubstore.get_reel_brand(d.name)).get("name", ""),
                }
            )
    return reels


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
        "channels": clean_ch,
    })
    return {"brand": brand, "brands": pubstore.list_brands()}


@app.post("/api/brands/delete")
def remove_brand(payload: dict = Body(...)):
    pubstore.delete_brand((payload.get("id") or "").strip())
    return {"brands": pubstore.list_brands()}


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
