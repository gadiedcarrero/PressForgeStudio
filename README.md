# PressForge Studio

Fábrica automatizada de reels históricos verticales (9:16) con IA.

> **Filosofía:** primero resolver un problema real propio (generar contenido
> histórico viral a escala) y, si demuestra utilidad, convertirlo en software
> vendible. Avanzar en iteraciones pequeñas, sin sobreingeniería.

## Estado: V1 — 1 reel end-to-end (CLI)

Desde un nicho (ej. *"muertes absurdas de reyes"*) el pipeline genera
automáticamente un `.mp4` 1080×1920 listo para publicar:

```
nicho → guion+storyboard → imágenes → voz → subtítulos → render
```

No incluye (todavía): dashboard, queue/batch, Postgres, publicación a redes.
Eso es V2–V5 y se construye **sobre** esta base modular.

## Arquitectura

Todo gira alrededor de *providers* desacoplados (interfaces en
[providers/base.py](pressforge/providers/base.py)). Hoy usan OpenAI; mañana
puedes cambiar cualquiera a un modelo local **sin tocar el pipeline**.

| Paso        | Interfaz            | Implementación V1            |
|-------------|---------------------|------------------------------|
| Guion       | `ScriptProvider`    | OpenAI (GPT, structured out) |
| Imágenes    | `ImageProvider`     | OpenAI `gpt-image-1`         |
| Voz         | `VoiceProvider`     | OpenAI TTS                   |
| Subtítulos  | `SubtitleProvider`  | Whisper (timestamps → ASS)   |
| Render      | `RenderProvider`    | FFmpeg (Ken Burns + subs)    |

La selección se hace por env vars (`*_PROVIDER`) en
[registry.py](pressforge/registry.py).

## Requisitos

- Python 3.11+
- **FFmpeg** en el PATH (`ffmpeg` y `ffprobe`)
- Una `OPENAI_API_KEY`

## Instalación

```powershell
# 1. FFmpeg (Windows, una vez)
winget install --id Gyan.FFmpeg -e

# 2. Entorno Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Configuración
cp .env.example .env   # y edita OPENAI_API_KEY
```

## Uso

```powershell
# Verifica que todo está listo (ffmpeg, ffprobe, API key)
python -m pressforge doctor

# Genera un reel
python -m pressforge make "muertes absurdas de reyes"

# Opciones
python -m pressforge make "guerras absurdas" --scenes 6 --voice nova --music assets/music/epic.mp3
```

El resultado queda en `output/<timestamp>-<slug>/` con el `reel.mp4`, las
imágenes, el audio, los subtítulos `.ass` y un `story.json` con el guion.

## Roadmap

- **V1** ✅ 1 reel funcional end-to-end (este código)
- **V2** Batch: generar N reels automáticamente
- **V3** Dashboard Next.js usable
- **V4** Programación automática
- **V5** Publicación automática a redes
- **V6** Reemplazo progresivo de APIs por modelos locales
