#!/bin/bash
# Arranca ComfyUI (servidor local de imágenes para PressForge). Déjalo abierto
# mientras generas reels con IMAGE_PROVIDER=local. Ctrl+C para cerrar.
cd "$HOME/ComfyUI" || { echo "No encuentro ~/ComfyUI"; read -r -p "Enter…"; exit 1; }
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "ComfyUI → http://127.0.0.1:8188  (déjalo abierto mientras produces)"
./venv/bin/python main.py
