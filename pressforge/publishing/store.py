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
    # brands: marcas/canales por nicho, cada una con sus cuentas conectadas.
    return {"posts": {}, "queue": [], "channels": {}, "brands": {}}


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


def set_post(
    reel_id: str, *, caption: str, hashtags: list[str], platforms: list[str],
    brand_id: str | None = None, entities: list[str] | None = None,
) -> dict:
    with _lock:
        data = _load()
        prev = data["posts"].get(reel_id, {})
        data["posts"][reel_id] = {
            "caption": caption,
            "hashtags": hashtags,
            "platforms": platforms,
            # conserva marca y entidades si no se pasan nuevas
            "brand_id": brand_id if brand_id is not None else prev.get("brand_id", ""),
            "entities": entities if entities is not None else prev.get("entities", []),
        }
        _save(data)
        return data["posts"][reel_id]


def set_reel_brand(reel_id: str, brand_id: str) -> None:
    with _lock:
        data = _load()
        post = data["posts"].setdefault(reel_id, {"caption": "", "hashtags": [], "platforms": []})
        post["brand_id"] = brand_id
        _save(data)


def get_reel_brand(reel_id: str) -> str:
    return get_post(reel_id).get("brand_id", "")


# ─── Marcas / canales por nicho ───
def list_brands() -> list[dict]:
    with _lock:
        return sorted(_load()["brands"].values(), key=lambda b: b.get("name", ""))


def get_brand(brand_id: str) -> dict:
    with _lock:
        return _load()["brands"].get(brand_id, {})


def upsert_brand(brand: dict) -> dict:
    with _lock:
        data = _load()
        bid = brand.get("id") or uuid.uuid4().hex[:12]
        brand = {**data["brands"].get(bid, {}), **brand, "id": bid}
        data["brands"][bid] = brand
        _save(data)
        return brand


def delete_brand(brand_id: str) -> None:
    with _lock:
        data = _load()
        data["brands"].pop(brand_id, None)
        _save(data)


def channels_for_reel(reel_id: str, platform: str) -> dict:
    """Credenciales de la plataforma según la marca del reel."""
    brand = get_brand(get_reel_brand(reel_id))
    return (brand.get("channels") or {}).get(platform, {})


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
