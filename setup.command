#!/bin/bash
# PressForge Studio — instalación (macOS). Doble clic una sola vez.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "════════════════════════════════════════"
echo "   PressForge Studio · instalación"
echo "════════════════════════════════════════"

# 1) Python 3
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Falta Python 3. Instálalo desde https://www.python.org/downloads/ y vuelve a abrir este archivo."
  read -r -p "Enter para cerrar…"; exit 1
fi

# 2) FFmpeg (necesario para el video)
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠ FFmpeg no está instalado."
  if command -v brew >/dev/null 2>&1; then
    echo "  Instalando con Homebrew…"; brew install ffmpeg
  else
    echo "  Primero instala Homebrew (https://brew.sh) y luego ejecuta: brew install ffmpeg"
    read -r -p "Enter para cerrar…"; exit 1
  fi
fi

# 3) Entorno e instalación
echo "→ Creando entorno e instalando dependencias…"
python3 -m venv .venv
./.venv/bin/python -m pip install --quiet --upgrade pip
./.venv/bin/python -m pip install --quiet -r requirements.txt

# 4) Configuración
if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ Creado .env  (ABRE el archivo .env y pega tu OPENAI_API_KEY)"
fi

echo ""
echo "✓ Listo. Ahora:"
echo "   1) Edita el archivo .env y pon tu OPENAI_API_KEY"
echo "   2) Doble clic en run.command para abrir la app"
read -r -p "Enter para cerrar…"
