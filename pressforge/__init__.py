"""PressForge Studio — fábrica de reels históricos con IA."""

import sys as _sys

# Windows usa cp1252 por defecto y `rich` revienta al imprimir Unicode (✓, …).
# Forzamos UTF-8 en la salida al importar el paquete, para cualquier punto de
# entrada (CLI, servidor web o scripts sueltos).
for _stream in (_sys.stdout, _sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

__version__ = "0.1.0"
