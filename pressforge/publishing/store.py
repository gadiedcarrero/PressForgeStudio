"""Persistencia local del sistema de publicación (data/publish.json).

Guarda tres cosas:
  - posts:    metadatos por reel (caption, hashtags, plataformas)
  - queue:    publicaciones programadas (qué reel, cuándo, dónde, estado)
  - channels: configuración de cada red (tokens) — local, fuera del repo
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

_DIR = Path("data")
_FILE = _DIR / "publish.json"
_lock = threading.RLock()


def _default() -> dict:
    return {"posts": {}, "queue": [], "channels": {}}


def _load() -> dict:
    if _FILE.exists():
        try:
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            for k, v in _default().items():
                data.setdefault(k, v)
            return data
        except Exception:  # noqa: BLE001
            return _default()
    return _default()


def _save(data: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Posts (caption/hashtags/plataformas por reel) ───
def get_post(reel_id: str) -> dict:
    with _lock:
        return _load()["posts"].get(reel_id, {})


def set_post(reel_id: str, *, caption: str, hashtags: list[str], platforms: list[str]) -> dict:
    with _lock:
        data = _load()
        data["posts"][reel_id] = {
            "caption": caption,
            "hashtags": hashtags,
            "platforms": platforms,
        }
        _save(data)
        return data["posts"][reel_id]


# ─── Cola programada ───
def list_queue() -> list[dict]:
    with _lock:
        return sorted(_load()["queue"], key=lambda x: x.get("scheduled_at", ""))


def add_queue_items(items: list[dict]) -> list[dict]:
    with _lock:
        data = _load()
        created = []
        for it in items:
            it = dict(it)
            it["id"] = uuid.uuid4().hex[:12]
            it.setdefault("status", "pending")
            data["queue"].append(it)
            created.append(it)
        _save(data)
        return created


def update_queue(qid: str, **fields) -> None:
    with _lock:
        data = _load()
        for it in data["queue"]:
            if it["id"] == qid:
                it.update(fields)
        _save(data)


def remove_queue(qid: str) -> None:
    with _lock:
        data = _load()
        data["queue"] = [it for it in data["queue"] if it["id"] != qid]
        _save(data)


def due_items(now_iso: str) -> list[dict]:
    """Items pendientes cuya hora programada ya llegó."""
    with _lock:
        return [
            it for it in _load()["queue"]
            if it.get("status") == "pending" and it.get("scheduled_at", "") <= now_iso
        ]


# ─── Canales ───
def get_channels() -> dict:
    with _lock:
        return _load()["channels"]


def set_channels(channels: dict) -> dict:
    with _lock:
        data = _load()
        data["channels"] = channels
        _save(data)
        return channels
