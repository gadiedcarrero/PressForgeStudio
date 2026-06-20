#!/bin/bash
# PressForge Studio — ARRANCA TODO (app + ComfyUI + Ollama) y, al cerrar esta
# ventana o pulsar Ctrl+C, CIERRA TODO. Doble clic para usar.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

PIDS=()
_CLEANED=0
cleanup() {
  [ "$_CLEANED" = 1 ] && return
  _CLEANED=1
  echo ""
  echo "⏹  Cerrando PressForge y todo lo local…"
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      pkill -P "$pid" 2>/dev/null   # primero los hijos
      kill "$pid" 2>/dev/null        # luego el proceso
    fi
  done
  # Asegura que los puertos queden libres AL INSTANTE para la próxima vez.
  sleep 1
  for port in 8000 8188; do
    p=$(lsof -ti tcp:$port 2>/dev/null)
    [ -n "$p" ] && kill -9 $p 2>/dev/null
  done
  echo "✓ Todo cerrado. Ya puedes cerrar la ventana."
  exit 0
}
trap cleanup INT TERM HUP EXIT

# Comprueba un puerto: si está en uso, cierra lo que lo ocupe (amable y luego a la
# fuerza) y ESPERA hasta confirmar que quedó libre antes de seguir.
free_port() {
  local port=$1
  if ! lsof -ti tcp:"$port" >/dev/null 2>&1; then
    echo "  ✓ puerto $port disponible"
    return 0
  fi
  echo "→ puerto $port EN USO — cerrando lo anterior antes de abrir…"
  kill $(lsof -ti tcp:"$port" 2>/dev/null) 2>/dev/null      # 1) intento amable
  sleep 1
  if lsof -ti tcp:"$port" >/dev/null 2>&1; then
    kill -9 $(lsof -ti tcp:"$port" 2>/dev/null) 2>/dev/null  # 2) a la fuerza
  fi
  # 3) esperar a que el puerto quede realmente libre (hasta ~6s)
  for _ in $(seq 1 12); do
    lsof -ti tcp:"$port" >/dev/null 2>&1 || { echo "  ✓ puerto $port liberado"; return 0; }
    sleep 0.5
  done
  echo "  ⚠ el puerto $port sigue ocupado; ciérralo a mano si la app no abre."
  return 1
}

echo "════════════════════════════════════════"
echo "   PressForge Studio · arrancando todo"
echo "════════════════════════════════════════"

if [ ! -d .venv ]; then
  echo "✗ No está instalado. Haz doble clic en setup.command primero."
  read -r -p "Enter para cerrar…"; exit 1
fi

# 1) Comprobar disponibilidad de puertos: si están en uso (arranque colgado),
#    cerrarlos y esperar a que queden libres ANTES de abrir de nuevo.
echo "→ comprobando puertos…"
free_port 8000   # app PressForge
free_port 8188   # ComfyUI

# 2) Ollama (guion local gratis) — arrancar solo si no responde ya.
if ! curl -s -o /dev/null http://localhost:11434/api/tags 2>/dev/null; then
  if command -v ollama >/dev/null 2>&1; then
    echo "→ arrancando Ollama (guion local)…"
    ollama serve >/tmp/pf_ollama.log 2>&1 &
    PIDS+=($!)
  fi
fi

# 3) ComfyUI (imágenes y video locales) — solo si está instalado.
if [ -f "$HOME/ComfyUI/venv/bin/python" ]; then
  echo "→ arrancando ComfyUI (imágenes/video local)…  http://127.0.0.1:8188"
  ( cd "$HOME/ComfyUI" && exec ./venv/bin/python main.py ) >/tmp/pf_comfyui.log 2>&1 &
  PIDS+=($!)
else
  echo "ℹ ComfyUI no está instalado: las imágenes/video locales no estarán (sí lo de pago)."
fi

# 4) La app PressForge.
echo "→ arrancando PressForge…  http://127.0.0.1:8000"
./.venv/bin/python -m pressforge serve >/tmp/pf_app.log 2>&1 &
PIDS+=($!)

# 5) Abrir el navegador cuando la app responda.
( for i in $(seq 1 60); do
    curl -s -o /dev/null http://127.0.0.1:8000 && break
    sleep 1
  done
  open "http://127.0.0.1:8000" ) &

echo ""
echo "✓ Todo arrancando (ComfyUI tarda ~20-40s en cargar sus modelos)."
echo "  • App:     http://127.0.0.1:8000"
echo "  • ComfyUI: http://127.0.0.1:8188"
echo ""
echo "  ⚠ DEJA ESTA VENTANA ABIERTA mientras trabajas."
echo "    Para CERRAR TODO: pulsa Ctrl+C aquí, o cierra esta ventana."
echo ""
echo "── registro de la app (en vivo) ──────────"
tail -f /tmp/pf_app.log &
PIDS+=($!)

# Mantener vivo el lanzador hasta Ctrl+C / cierre de ventana.
while true; do sleep 3600 & wait $!; done
