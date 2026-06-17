# PressForge Studio

Fábrica automatizada de reels históricos verticales (9:16) con IA.
Genera guiones, voz, imágenes, subtítulos y vídeo listo para publicar — y los
organiza por **marca/canal**, con **programación** y **publicación** a redes.

> **Repo:** https://github.com/gadiedcarrero/PressForgeStudio
> **Filosofía:** resolver primero un problema real propio (producir contenido
> histórico viral a escala) y, si funciona, convertirlo en software vendible.
> Iteraciones pequeñas, sin sobreingeniería.

📄 ¿Vienes de otra PC o retomas el proyecto? Lee **[docs/CONTEXT.md](docs/CONTEXT.md)** —
tiene el estado completo, las decisiones y los próximos pasos.
🎨 ¿Quieres generar logos/banners/imágenes con IA a la carta? Ver **[docs/GENERAR_IMAGENES.md](docs/GENERAR_IMAGENES.md)**.

---

## Qué hace (estado actual)

Desde un tema, en 2 pasos: **genera el guion → lo revisas/editas → produces el reel**.

**5 modos de creación** (todos muestran el guion editable antes de gastar en el render):
| Modo | Qué hace | Fuente |
|------|----------|--------|
| ✍️ Inventar | La IA crea una historia desde un nicho | — (puede alucinar; por eso editas) |
| 📝 Mi guion | Tú escribes, la IA solo pule y divide en escenas | Tu texto (no inventa) |
| 🏛️ Histórico | Busca artículos **reales** en Wikipedia y eliges cuáles | ✅ Wikipedia, cita fuente |
| 📅 Qué pasó hoy | Efemérides reales de un día como hoy, eliges cuáles | ✅ Wikipedia "On this day" |
| 🔥 Curiosidades virales | Datos sorprendentes de Reddit (TIL/history), eliges cuáles | ✅ Reddit (RSS), cita fuente |

**Producción de cada reel:** guion con **hook fuerte** y **narración continua** → imágenes IA (auto-escaladas: ~1 cada 4 s) con **estilo visual** elegible (cinematográfico, fotorrealista, colores vivos, óleo, ilustración, vintage, anime, **3D Pixar**) y **consistencia de personajes** (la misma persona en cada escena) → **voz IA (OpenAI o ElevenLabs premium**, con modelo y velocidad) → subtítulos estilo TikTok → render FFmpeg (Ken Burns + música + **outro con cola y fundidos**) → `reel.mp4` 1080×1920.

También: **imagen de referencia por escena** (recrea una foto real en el estilo del vídeo) y **Brand Kit por marca** (logo + banners, versionados, en Drive).

**Organización y publicación:**
- **Marcas / Canales**: una marca por nicho (terror, dietas, historia…), cada una con su nicho, estilo (voz/música/hashtags) y **sus propias cuentas** de YouTube/Instagram/Facebook/TikTok.
- **Library**: editor por reel (caption + hashtags + plataformas), asignar marca, publicar/programar.
- **Programación en lote**: "hago 5 reels → publico 1 al día" → cola automática.
- **Agenda**: lo programado, con estado. Un motor en segundo plano publica a su hora.
- **Música**: biblioteca con tags; el modo `Auto` elige la pista según el tono del guion.

> ⚠️ **Publicación automática real**: hoy funciona en modo **"manual asistido"**
> (prepara el caption + descarga del mp4 para que lo pegues). Las APIs reales
> (YouTube → Meta → TikTok) se enchufan después; la arquitectura ya las soporta.
> WhatsApp **no** tiene API para publicar en feed (es solo mensajería).

---

## Requisitos
- **Python 3.11+**
- **FFmpeg** (`ffmpeg` y `ffprobe`). No hace falta tenerlo en el PATH: la app lo
  localiza solo (winget en Windows, Homebrew en Mac); o fíjalo con `FFMPEG_DIR`.
- Una **`OPENAI_API_KEY`** (cubre guion, imágenes y voz OpenAI). Pago por uso →
  https://platform.openai.com/api-keys
- *(Opcional)* **`ELEVENLABS_API_KEY`** para la voz premium (se pone en Ajustes →
  API Keys). El proveedor/voz/modelo/velocidad se eligen en **Crear**.
- *(Opcional)* **`STORAGE_DIR`** apuntando a una carpeta de Google Drive para
  compartir marcas, reels, música y brand kits entre tus PCs (Mac ↔ Windows).

---

## Setup en una PC nueva (desde cero)

```powershell
# 1. Clonar
git clone https://github.com/gadiedcarrero/PressForgeStudio.git
cd PressForgeStudio

# 2. FFmpeg (Windows, una vez)
winget install --id Gyan.FFmpeg -e
#   (macOS: brew install ffmpeg · Linux: apt install ffmpeg)
#   Reinicia la terminal para que el PATH tome ffmpeg.

# 3. Entorno Python
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # Windows
#   source .venv/bin/activate           # macOS/Linux
pip install -r requirements.txt

# 4. Configuración (el .env NO está en el repo, créalo)
copy .env.example .env                  # Windows  (cp en mac/linux)
#   edita .env y pon tu OPENAI_API_KEY

# 5. Verifica el entorno
python -m pressforge doctor             # debe dar todo ✓

# 6. Arranca la interfaz web
python -m pressforge serve              # http://127.0.0.1:8000
```

### 🍎 macOS (Apple Silicon M1/M2/M3) — modo fácil (doble clic)

Ideal para correrlo en una Mac. Una sola vez:

```bash
# 1. Requisitos (una vez): Homebrew + FFmpeg
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg python git

# 2. Clonar
git clone https://github.com/gadiedcarrero/PressForgeStudio.git
cd PressForgeStudio
```

Luego, en Finder, dentro de la carpeta:
1. Doble clic en **`setup.command`** (instala todo). *La primera vez, si macOS bloquea el archivo: clic derecho → Abrir → Abrir.*
2. Abre **`.env`** y pega tu `OPENAI_API_KEY`.
3. Doble clic en **`run.command`** → se abre la app en el navegador.

> Para volver a usarla otro día: solo **doble clic en `run.command`**.

### Importante al cambiar de PC
Estos NO viajan en el repo (están en `.gitignore`):
- **`.env`** → recréalo con tu `OPENAI_API_KEY`.
- **`output/`** → los reels generados (se regeneran; pesan mucho).
- **`data/`** → tus **marcas, canales (tokens) y la cola de publicación**. Si quieres
  conservarlos entre PCs, copia manualmente la carpeta `data/` (contiene
  `publish.json`). Si no, vuelves a crear las marcas en la pestaña **Marcas**.
- **`assets/music/`** sí viaja si lo commiteas; las pistas grandes quizá prefieras
  copiarlas a mano.

---

## Uso

### Interfaz web (recomendado)
```powershell
python -m pressforge serve
```
Abre http://127.0.0.1:8000. Menú lateral: **Crear · Library · Música · Agenda · Marcas**.
> El motor de programación publica **con la app abierta** (`serve` corriendo).

### CLI
```powershell
python -m pressforge make "muertes absurdas de reyes"   # crea un reel (modo Inventar)
python -m pressforge make "guerras absurdas" --scenes 0 --voice nova --music auto
python -m pressforge music      # lista las pistas de la biblioteca
python -m pressforge doctor     # chequea ffmpeg, ffprobe, API key
python -m pressforge serve      # levanta la web
```
`--scenes 0` = número de imágenes automático según la longitud del guion.

---

## Estructura del proyecto

```
pressforge/
  config.py            Settings desde .env (modelos, providers, voz, render…)
  models.py            Story, Scene, SourceFact, RenderJob… + serialización
  pipeline.py          Orquestador: generate_stories() / produce_reel()
  registry.py          Selección de providers por env var
  subtitles.py         Genera el .ass estilo TikTok (wrap a 2 líneas)
  music_library.py     Biblioteca de música con tags + matching por mood
  ffmpeg_utils.py      ffprobe + helper de ffmpeg
  cli.py / __main__.py CLI (make / serve / music / doctor)
  providers/           Capa desacoplada (un provider por paso)
    base.py            Protocols: Script/Image/Voice/Subtitle/Render/Music/Research
    openai_script.py   Guion (structured output) — generate/refine/from_source
    openai_image.py    gpt-image-1 (+ reintento ante filtro de seguridad)
    openai_voice.py    TTS
    whisper_subtitle.py Whisper word-timestamps
    ffmpeg_render.py   Ken Burns + concat + subs + mezcla de música
    local_music.py     MusicProvider de biblioteca local
    wikipedia_research.py  Búsqueda + "on this day" (REST Wikimedia, sin API key)
  publishing/          Sistema de publicación
    store.py           data/publish.json: posts, cola, marcas/canales
    base.py            PublishProvider + PublishResult
    manual.py          Publicador "manual asistido" (prepara caption.txt)
    scheduler.py       Motor en hilo de fondo (revisa la cola y publica)
  web/
    app.py             FastAPI (toda la API JSON)
    index.html         La interfaz (una sola página, Tailwind via CDN)
assets/                logo, favicon, assets/music/ (biblioteca)
output/                reels generados (gitignored)
data/                  marcas, canales, cola (gitignored)
docs/CONTEXT.md        estado del proyecto y próximos pasos
```

Todo es modular: cada paso es un *provider* intercambiable (OpenAI hoy → modelo
local mañana) seleccionable por env vars en `.env`, sin tocar el pipeline.

---

## Roadmap
- **V1** ✅ reel end-to-end · **V2** ✅ múltiples reels · **V3** ✅ dashboard web
- **V4** 🟡 programación (cola + agenda hechas; falta correr 24/7 sin la app abierta)
- **V5** 🟡 publicación a redes (base lista; faltan las APIs reales por plataforma)
- **V6** ⬜ reemplazo progresivo de APIs por modelos locales

Detalle y próximos pasos concretos en **[docs/CONTEXT.md](docs/CONTEXT.md)**.
