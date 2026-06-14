"""MusicProvider con biblioteca local + tags.

Lee los audios de `assets/music/` y sus tags de `library.json` (ver
`music_library.py`). La selección `auto` cruza el "mood" musical que sugiere el
guion con los tags de cada pista. Cero coste, cero riesgo legal.

Cuando quieras música generada por IA, basta con añadir otro MusicProvider
(MusicGen vía Replicate, Stable Audio…) con la misma interfaz.
"""
from __future__ import annotations

from pathlib import Path

from ..music_library import MusicLibrary


class LocalLibraryMusicProvider:
    def __init__(self) -> None:
        self.lib = MusicLibrary()

    def list_tracks(self) -> list[str]:
        return self.lib.track_files()

    def get_track(self, *, mood: str | None = None, track: str | None = None) -> Path | None:
        # Pista pedida explícitamente (por nombre o sin extensión).
        if track:
            for n in self.lib.track_files():
                if n == track or Path(n).stem.lower() == track.lower():
                    return self.lib.dir / n
            return None  # pidió una que no existe → avisar, no elegir otra

        name = self.lib.match(mood)
        return self.lib.dir / name if name else None
