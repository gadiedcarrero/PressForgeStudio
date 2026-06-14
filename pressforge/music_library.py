"""Biblioteca de música con metadatos (tags) en un sidecar JSON.

Los archivos de audio viven en `assets/music/`. Los tags se guardan en
`assets/music/library.json` (`{ "epic.mp3": {"tags": ["epic","war"]} }`), de
modo que la IA pueda elegir la pista adecuada cruzando el "mood" que sugiere el
guion con los tags de cada pista.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

_MUSIC_DIR = Path("assets/music")
_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2}


class MusicLibrary:
    def __init__(self, directory: Path = _MUSIC_DIR) -> None:
        self.dir = directory
        self.meta_path = directory / "library.json"

    # --- metadatos ---
    def _load(self) -> dict:
        if self.meta_path.exists():
            try:
                return json.loads(self.meta_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _save(self, meta: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- pistas ---
    def track_files(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted(p.name for p in self.dir.iterdir() if p.suffix.lower() in _EXTS)

    def entries(self) -> list[dict]:
        """Pistas enriquecidas con sus tags, para la UI."""
        meta = self._load()
        return [
            {"name": n, "tags": meta.get(n, {}).get("tags", []), "url": f"/music/{n}"}
            for n in self.track_files()
        ]

    def set_tags(self, name: str, tags: list[str]) -> None:
        meta = self._load()
        clean = [t.strip().lower() for t in tags if t.strip()]
        meta.setdefault(name, {})["tags"] = clean
        self._save(meta)

    def delete(self, name: str) -> bool:
        f = self.dir / Path(name).name
        existed = f.exists()
        if existed:
            f.unlink()
        meta = self._load()
        if meta.pop(name, None) is not None:
            self._save(meta)
        return existed

    # --- selección por mood ---
    def match(self, mood: str | None) -> str | None:
        """Devuelve la pista que mejor casa con el mood (por tags y nombre).

        El mood viene como lista de tags ordenada por prioridad (el guion pone
        primero el más representativo), así que pesamos por posición: el primer
        tag vale más. Sin coincidencias o sin mood → una al azar.
        """
        files = self.track_files()
        if not files:
            return None
        if not mood or not mood.strip():
            return random.choice(files)

        ordered = [w for w in re.split(r"[^a-z0-9]+", mood.lower()) if len(w) > 2]
        if not ordered:
            return random.choice(files)
        weights: dict[str, int] = {}
        n = len(ordered)
        for i, w in enumerate(ordered):
            weights[w] = max(weights.get(w, 0), n - i)  # primero pesa n, último 1

        meta = self._load()
        best, best_score = None, 0
        for name in files:
            hay = set()
            for t in meta.get(name, {}).get("tags", []):
                hay |= _tokens(t)
            hay |= _tokens(Path(name).stem)
            score = sum(w for tok, w in weights.items() if tok in hay)
            if score > best_score:
                best, best_score = name, score
        return best or random.choice(files)
