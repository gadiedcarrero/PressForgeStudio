"""Motor de programación: revisa la cola y publica lo que toca.

Corre en un hilo de fondo dentro del servidor web. Cada minuto busca items
cuya hora ya llegó y los publica con el `PublishProvider` de su plataforma.

Hoy todas las plataformas usan el publicador manual (prepara el caption). Para
activar una red real, basta con registrar su provider en PUBLISHERS.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

from . import store
from .manual import ManualPublisher

_OUTPUT = Path("output")

# Un publicador por plataforma. Hoy todos manuales; se reemplazan uno a uno.
_MANUAL = ManualPublisher()
PUBLISHERS: dict[str, object] = {
    "youtube": _MANUAL,
    "instagram": _MANUAL,
    "facebook": _MANUAL,
    "tiktok": _MANUAL,
    "manual": _MANUAL,
}

_started = False


def get_publisher(platform: str):
    return PUBLISHERS.get(platform, _MANUAL)


def _process_once() -> None:
    now = datetime.now().isoformat(timespec="minutes")
    for it in store.due_items(now):
        reel_id = it.get("reel_id", "")
        platform = it.get("platform", "manual")
        reel_path = _OUTPUT / reel_id / "reel.mp4"
        post = store.get_post(reel_id)
        try:
            res = get_publisher(platform).publish(
                reel_path=reel_path,
                caption=post.get("caption", ""),
                hashtags=post.get("hashtags", []),
                platform=platform,
                channel=store.get_channels().get(platform, {}),
            )
            store.update_queue(
                it["id"], status=res.status, detail=res.detail,
                url=res.url, published_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            store.update_queue(it["id"], status="failed", detail=str(exc))


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            try:
                _process_once()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(60)

    threading.Thread(target=loop, daemon=True, name="pf-scheduler").start()
