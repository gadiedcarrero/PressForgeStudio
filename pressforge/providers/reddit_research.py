"""Investigación de curiosidades virales en Reddit (vía feeds RSS/Atom).

Reddit bloquea (403) sus endpoints `.json` sin OAuth, pero los feeds RSS públicos
siguen abiertos. Leemos r/todayilearned + r/history (configurable) y devolvemos
`SourceFact`: el título del post es el dato (TIL obliga a citar fuente real) y de
cada entrada sacamos el enlace de origen.

Para cambiar/añadir subreddits basta con pasar otra lista.
"""
from __future__ import annotations

import html
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from ..models import SourceFact

# Reddit responde 403 al UA por defecto de urllib; uno de navegador sí pasa en RSS.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_TIMEOUT = 20
_DEFAULT_SUBS = ["todayilearned", "history"]
_ATOM = "{http://www.w3.org/2005/Atom}"

_TIL_PREFIX = re.compile(r"^\s*TIL(?:\s+that|\s+about|\s*:|,)?\s+", re.IGNORECASE)
# El href del ancla "[link]" del contenido apunta a la fuente externa del post.
_SRC_LINK = re.compile(r'href="([^"]+)"[^>]*>\s*\[link\]', re.IGNORECASE)


class RedditResearch:
    def __init__(self, subreddits: list[str] | None = None) -> None:
        self.subs = subreddits or _DEFAULT_SUBS

    # --- HTTP ---
    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:  # límite de tasa: espera y reintenta
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError as exc:
                if isinstance(getattr(exc, "reason", None), ssl.SSLError):
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
                        return resp.read()
                raise
        raise RuntimeError("Reddit no respondió tras varios intentos.")

    # --- Curiosidades ---
    def curiosities(self, *, query: str = "", limit: int = 20,
                    period: str = "year") -> list[SourceFact]:
        """Posts de curiosidades de los subreddits configurados.

        - Sin `query`: los más votados del periodo (top).
        - Con `query`: búsqueda dentro de esos subreddits.
        `period`: hour/day/week/month/year/all.
        """
        multi = "+".join(self.subs)
        if query.strip():
            qs = urllib.parse.urlencode({
                "q": query.strip(), "restrict_sr": "on", "sort": "top", "t": period,
            })
            url = f"https://www.reddit.com/r/{multi}/search/.rss?{qs}"
        else:
            url = f"https://www.reddit.com/r/{multi}/top/.rss?t={period}"

        try:
            raw = self._get(url)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"Reddit respondió {exc.code} (puede ser límite de tasa; reintenta en un momento)."
            )

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise RuntimeError(f"No pude leer el feed de Reddit: {exc}")

        out: list[SourceFact] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = html.unescape((entry.findtext(f"{_ATOM}title") or "").strip())
            title = _TIL_PREFIX.sub("", title)
            if len(title) < 15:
                continue
            content = entry.findtext(f"{_ATOM}content") or ""
            link_el = entry.find(f"{_ATOM}link")
            permalink = link_el.get("href") if link_el is not None else ""
            m = _SRC_LINK.search(content)
            url_src = html.unescape(m.group(1)) if m else permalink
            if not url_src or "redd.it" in url_src or "reddit.com" in url_src:
                url_src = permalink
            out.append(SourceFact(title=title, extract=title, url=url_src))
            if len(out) >= max(1, limit):
                break
        return out
