"""Investigación de hechos reales en Wikipedia / Wikimedia.

Dos capacidades:
  - search(tema)        -> artículos relevantes con su extracto y URL
  - on_this_day(mm, dd) -> eventos históricos reales de un día como hoy

Usa las APIs públicas de Wikipedia (sin API key). Wikimedia exige un
User-Agent descriptivo. Devuelve `SourceFact`, que el ScriptProvider convierte
en guion SIN inventar (y la UI muestra la fuente citada).

Para cambiar de fuente en el futuro (otra enciclopedia, API histórica…), basta
con otra clase que devuelva `SourceFact`.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from ..config import get_settings
from ..models import SourceFact

_UA = "PressForgeStudio/0.1 (https://github.com/gadiedcarrero/PressForgeStudio)"
_TIMEOUT = 20


class WikipediaResearch:
    def __init__(self) -> None:
        self.lang = (get_settings().language or "es").split("-")[0]

    # --- HTTP ---
    def _get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            # Fallback solo si falla la verificación TLS (p. ej. reloj del sistema
            # desfasado hace ver los certificados como expirados). Wikipedia es
            # lectura pública, así que el riesgo de no verificar aquí es nulo.
            if isinstance(getattr(exc, "reason", None), ssl.SSLError):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            raise

    # --- Búsqueda por tema ---
    def search(self, topic: str, *, limit: int = 3) -> list[SourceFact]:
        """Artículos relevantes para el tema, con extracto introductorio y URL."""
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts|info",
            "inprop": "url",
            "exintro": "1",
            "explaintext": "1",
            "exchars": "1200",
            "generator": "search",
            "gsrsearch": topic,
            "gsrlimit": str(max(1, limit)),
            "gsrnamespace": "0",
        }
        url = f"https://{self.lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
        data = self._get(url)
        pages = (data.get("query") or {}).get("pages") or {}
        facts = []
        for p in sorted(pages.values(), key=lambda x: x.get("index", 999)):
            extract = (p.get("extract") or "").strip()
            if not extract:
                continue
            facts.append(
                SourceFact(
                    title=p.get("title", ""),
                    extract=extract,
                    url=p.get("fullurl", ""),
                )
            )
        return facts

    # --- Efemérides ---
    def on_this_day(self, month: int, day: int, *, limit: int = 30) -> list[SourceFact]:
        """Eventos históricos reales ocurridos un día como hoy (varios años)."""
        url = (
            f"https://{self.lang}.wikipedia.org/api/rest_v1/feed/onthisday/events/"
            f"{month:02d}/{day:02d}"
        )
        data = self._get(url)
        out = []
        for ev in (data.get("events") or [])[:limit]:
            pages = ev.get("pages") or []
            page = pages[0] if pages else {}
            page_url = (((page.get("content_urls") or {}).get("desktop") or {}).get("page")) or ""
            out.append(
                SourceFact(
                    title=page.get("normalizedtitle") or page.get("title") or "",
                    extract=ev.get("text", ""),
                    url=page_url,
                    year=ev.get("year"),
                )
            )
        return out
