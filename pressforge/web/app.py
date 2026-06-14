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
import threading
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..models import story_from_dict, story_to_dict
from ..pipeline import generate_stories, produce_reel

OUTPUT = Path("output")
WEB_DIR = Path(__file__).parent
MUSIC_DIR = Path("assets/music")
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
_MAX_MUSIC_BYTES = 50 * 1024 * 1024  # 50 MB

app = FastAPI(title="PressForge Studio")

# Estado en memoria (suficiente para uso local de 1 usuario).
_jobs: dict[str, dict] = {}        # render jobs en curso/terminados
_scripts: dict[str, dict] = {}     # guiones generados (editables antes de producir)
_lock = threading.Lock()


ASSETS_DIR = Path("assets")

OUTPUT.mkdir(exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(OUTPUT)), name="output")
app.mount("/music", StaticFiles(directory=str(MUSIC_DIR)), name="music")
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    ico = ASSETS_DIR / "favicon.ico"
    return FileResponse(ico) if ico.exists() else JSONResponse({}, status_code=404)


# ─── Paso 1: generar guion(es) para revisar/editar ───────────────────────────
@app.post("/api/scripts")
def create_scripts(payload: dict = Body(...)):
    mode = (payload.get("mode") or "invent").strip()
    raw_scenes = payload.get("scenes")
    scenes = max(3, min(18, int(raw_scenes))) if raw_scenes else None  # None = auto
    count = max(1, min(3, int(payload.get("count") or 1)))
    niche = (payload.get("niche") or "").strip() or None
    extra = (payload.get("extra") or "").strip() or None
    user_script = (payload.get("user_script") or "").strip() or None

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
def _run_job(job_id: str, story_dict: dict, voice: str, music: str) -> None:
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
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"status": "running", "events": [], "title": story_dict.get("title", "")}
    threading.Thread(
        target=_run_job, args=(job_id, dict(story_dict), voice, music), daemon=True
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


@app.get("/api/reels")
def list_reels():
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
                }
            )
    return reels
