"""Contrato de los publicadores (uno por red social)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class PublishResult:
    ok: bool
    status: str  # 'ready' (preparado/manual) | 'published' (publicado real) | 'failed'
    detail: str = ""
    url: str = ""


@runtime_checkable
class PublishProvider(Protocol):
    def publish(
        self,
        *,
        reel_path: Path,
        caption: str,
        hashtags: list[str],
        platform: str,
        channel: dict,
    ) -> PublishResult:
        """Publica (o prepara) el reel en una plataforma."""
        ...
