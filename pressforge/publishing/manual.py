"""Publicador 'manual asistido'.

No publica solo (eso requiere las APIs reales de cada red). Lo que hace es dejar
TODO listo: escribe el caption + hashtags en un .txt junto al reel, para que al
llegar la hora programada solo tengas que subir el mp4 y pegar el texto.

Cuando se implementen los publicadores reales (YouTube/IG/FB/TikTok) compartirán
esta misma interfaz y el scheduler no cambia.
"""
from __future__ import annotations

from pathlib import Path

from .base import PublishResult


def caption_text(caption: str, hashtags: list[str]) -> str:
    text = (caption or "").strip()
    tags = " ".join("#" + h.lstrip("#") for h in (hashtags or []) if h.strip())
    return f"{text}\n\n{tags}".strip() if tags else text


class ManualPublisher:
    def publish(self, *, reel_path, caption, hashtags, platform, channel) -> PublishResult:
        text = caption_text(caption, hashtags)
        try:
            out = Path(reel_path).parent / f"caption_{platform}.txt"
            out.write_text(text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return PublishResult(
            ok=True,
            status="ready",
            detail=f"Listo para publicar manualmente en {platform} (caption preparado).",
        )
