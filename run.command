#!/bin/bash
# PressForge Studio — arranque (macOS). Doble clic para abrir la app.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -d .venv ]; then
  echo "✗ No está instalado todavía. Haz doble clic en setup.command primero."
  read -r -p "Enter para cerrar…"; exit 1
fi

# Abre el navegador cuando el servidor esté listo
( sleep 3; open "http://127.0.0.1:8000" ) &

echo "PressForge Studio → http://127.0.0.1:8000"
echo "(Deja esta ventana abierta mientras trabajas. Cierra con Ctrl+C.)"
./.venv/bin/python -m pressforge serve
