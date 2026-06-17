# PressForge Studio — Contexto del proyecto

> Documento para **retomar el proyecto desde cualquier PC** (y para que Claude
> recupere contexto). Resume qué es, cómo está construido, las decisiones
> tomadas, el estado actual y los próximos pasos. Última actualización tras el
> commit `97117d8` (voz ElevenLabs + estilos visuales + Reddit + consistencia de
> personajes + imágenes de referencia + narración continua + outro con fundidos +
> brand kits versionados en Drive).

---

## 1. Visión

Herramienta para **generar reels históricos verticales (9:16) virales a escala**,
para uso propio primero y posible producto después. El usuario (y su esposa, que
administrará el negocio) quiere montar **varios canales por nicho** (terror,
historia, ciencia, dietas…) y publicar/programar contenido casi automático.

Principios: iteraciones pequeñas, **arquitectura modular** (cada paso es un
provider intercambiable), evitar sobreingeniería, y **fidelidad a los hechos**
cuando se trata de historia real.

---

## 2. Stack y arquitectura

- **Backend/pipeline:** Python. **Web:** FastAPI + una sola `index.html` (Tailwind por CDN, dark mode, estilo "Suno" con sidebar). **Render:** FFmpeg. **IA:** OpenAI (guion `gpt-4o`, imágenes `gpt-image-1`, voz `gpt-4o-mini-tts`, subtítulos `whisper-1`) y **ElevenLabs** (voz premium). **Fuentes:** Wikipedia/Wikimedia REST y **Reddit** (RSS), ambas sin API key.
- **Providers desacoplados** (`pressforge/providers/base.py`, `Protocol`s) seleccionables por env vars en `registry.py` (+ overrides de la UI en `secrets.json`): Script, Image, Voice, Subtitle, Render, Music, Research. Mañana se cambia cualquiera a modelo local sin tocar el pipeline.
- **ffmpeg/ffprobe** se localizan solos aunque no estén en el PATH (`ffmpeg_utils._resolve`: PATH → `FFMPEG_DIR` → ubicaciones típicas de winget/Homebrew), así el servidor no depende de cómo se arranque.
- **Flujo de 2 pasos:** `generate_stories(mode,…)` → guion(es) editables → `produce_reel(story,…)` (imágenes/voz/subs/render). En la web son `/api/scripts` y `/api/produce`.
- **Publicación** (`pressforge/publishing/`): store en `data/publish.json`, publicador `manual`, `scheduler` en hilo de fondo. Un `PublishProvider` por red (hoy todos manuales).

### Mapa de archivos clave
- `pipeline.py` — `generate_stories`, `generate_story`, `generate_story_from_fact`, `produce_reel`, `generate_reel` (CLI), `auto_scene_count`, `human_date`, `_fallback_image`, `_with_characters` (inyecta descripción de personaje en el prompt), `_finalize_narration` (puntuación final), `_OUTRO_TAIL` (cola tras la voz).
- `providers/openai_script.py` — `generate` (inventar), `refine` (mi guion), `from_source` (Wikipedia/Reddit), `select_events` (efemérides), `describe` (entidades). Doctrinas inyectadas en los 3 prompts: `_HOOK_DOCTRINE` (hook), `_CHARACTER_DOCTRINE` (biblia de personajes), `_NARRATION_DOCTRINE` (narración continua + cierre con entonación final).
- `providers/openai_image.py` — gpt-image-1 con **reintento suavizado** y `ImageBlockedError`. `STYLES` (estilos visuales: cinematic/photo/vivid/painting/illustration/vintage/anime/3d) + `_FORMAT_SAFETY` siempre. `generate(prompt, out, reference=None)`: con `reference` usa `images.edit` para recrear la composición de una foto en el estilo elegido.
- `providers/elevenlabs_voice.py` — voz premium. `synthesize` (modelo + **velocidad** configurables vía `voice_settings`), `list_voices` (cuenta), `library_voices` (biblioteca pública, filtros idioma/uso/acento). Key BYOK, fallback TLS.
- `providers/wikipedia_research.py` — `search(tema)` y `on_this_day(mm,dd)`. Fallback TLS.
- `providers/reddit_research.py` — `curiosities(query, …)` lee **feeds RSS** de r/todayilearned + r/history (Reddit bloquea el `.json` sin OAuth; el RSS sigue abierto). Devuelve `SourceFact` con su fuente.
- `branding.py` — `generate_brand_kit` (versionado: 1 carpeta por intento) y `list_kits`. Guarda en **Drive** (`config.branding_path()`).
- `subtitles.py` — ASS estilo TikTok, **wrap a 2 líneas** según ancho del frame.
- `providers/ffmpeg_render.py` — Ken Burns por escena, concat, subs ASS, mezcla de audio. **Outro:** sin `-shortest`, cola tras la voz, **fade out de vídeo y de música**.
- `music_library.py` — tags en `library.json`, matching ponderado por mood. En Drive si hay `STORAGE_DIR`.
- `publishing/store.py` — posts, cola, **marcas** (CRUD), reel→marca, `channels_for_reel`.
- `models.py` — `Story`/`Scene` + `Character`; `Scene.characters` (quién aparece) y `Scene.reference` (foto de referencia). `story_to_dict`/`story_from_dict` los serializan para la UI.
- `web/app.py` — toda la API. `web/index.html` — toda la UI (vistas: Crear, Library, Música, Agenda, Marcas + modal genérico).

---

## 3. Funcionalidades implementadas

- **Crear** (5 modos): Inventar · Mi guion · Histórico (Wikipedia) · Qué pasó hoy (efemérides) · **Curiosidades virales (Reddit)**. Los modos con fuente (Histórico/Efemérides/Reddit) **listan primero** los resultados y el usuario **elige cuáles** convertir en guion (no se gasta IA en lo que no interesa). Variantes (1-3) en Inventar.
- **Selector de voz en Crear:** proveedor (OpenAI / **ElevenLabs**) + voz (dropdown de la cuenta), **modelo** ElevenLabs (Multilingüe v2 / Flash) y **velocidad** (0.9–1.2; arregla voces "cinematic" lentas). Preview ▶/⏹ (play/stop) tanto en el selector como en la biblioteca. **Explorar biblioteca** de voces de ElevenLabs con filtros (idioma/uso/acento) y preview gratis.
- **Estilo visual** (selector en Crear, persistente): cinematográfico histórico · fotorrealista · colores vivos · pintura óleo · ilustración · vintage/sepia · anime · **3D animado (Pixar/Disney)**. Las barandillas de seguridad y el 9:16 se aplican siempre.
- **Guion editable** (acordeón si hay varios): título, hook, escenas (narración + prompt de imagen), CTA, fecha y fuente citada. **Hook fuerte** garantizado por la doctrina del hook.
- **Consistencia de personajes (biblia de personajes):** la IA lee toda la historia, detecta personajes (protagonista y secundarios; misma persona en distinta etapa = un solo personaje) y les fija una descripción visual. En cada imagen se **repite** esa descripción para que salgan iguales; prohíbe meter personas no descritas. En la UI: bloque **Personajes** editable + **chips por escena** para marcar quién aparece. (Límite: gpt-image-1 usa descripción de texto, da coherencia, no clon exacto.)
- **Imagen de referencia por escena:** subes una foto y esa escena se recrea (composición/poses/emoción) en el estilo del vídeo (gpt-image-1 `images.edit`). Útil para fotos icónicas reales. Se guardan en `data/refs` (Drive).
- **Narración continua + cierre:** las narraciones de las escenas forman UNA narración fluida (una sola síntesis TTS), no frases sueltas; la última frase cierra con **entonación final** (puntuación garantizada).
- **Producción:** nº de imágenes **auto-escalado** por longitud (~1 cada 4 s, tope 18). Subtítulos sin desbordarse. Resiliencia ante el filtro de seguridad de imágenes (reintento → reutiliza anterior → neutral → sólido). **Outro:** ~2.5 s de cola tras la voz + **fundido a negro** del vídeo y **fundido** de la música.
- **Música:** subir + tags (lápiz para editar con sugerencias), selección `Auto` por mood. Biblioteca en Drive.
- **Marcas/Canales:** una marca por nicho con nicho, hashtags/voz/música por defecto y cuentas por plataforma. Reels se asignan a marca (hereda estilo); Library tiene badge y filtro por marca. Marcas actuales: **Curiosidades Mitológicas**, **Reflexiones de Vida** (parábolas/moralejas), **Historias Reales** (casos verídicos/injusticias).
- **Brand Kit (logo + banners) por marca, versionado:** "Generar logo + banners con IA" crea una **nueva versión** cada vez (no sobrescribe); se ven como **acordeón** de generaciones (la más nueva arriba) y se guardan en **Drive** (`branding/<marca>/<intento>/`), accesibles desde cualquier PC. Recorta a las medidas de YouTube/Facebook/Instagram/X.
- **Publicación:** editor de reel (caption auto-sugerido + hashtags + plataformas), **publicar ahora** (manual asistido) y **programar** (individual o en lote: N reels, 1/día). **Agenda** con estado. Scheduler en hilo de fondo. Descarga con el **título** del vídeo (`/api/reels/{id}/download`).
- **Internal linking:** botón "Generar con IA" en el editor → descripción + hashtags + **entidades clave** (`describe()` en el ScriptProvider). `/api/reels/{id}/related` cruza esas entidades con otros reels (substring sobre su story.json) para sugerir **reels relacionados** e insertar referencias en el caption (telaraña Medusa→Poseidón→…).
- **Branding:** logo isotipo + favicon; iconos SVG outline monocromos.

---

## 4. Decisiones importantes (el "por qué")

- **Fuentes de contenido:** **Wikipedia/Wikimedia** (hechos históricos, citable) y **Reddit** (curiosidades virales). **Quora NO** (sin API, bloquea scraping, su ToS lo prohíbe → riesgo legal al vender, contenido no verificable). Reddit también bloquea su `.json` sin OAuth, pero los **feeds RSS** públicos siguen abiertos → se usan esos (r/todayilearned obliga a citar fuente real). TIL viene en inglés; la IA lo convierte a español al generar el guion.
- **Consistencia de personajes por DESCRIPCIÓN de texto** (no por imagen de referencia de cara), porque gpt-image-1 no tiene "character reference". Da personajes coherentes/reconocibles, no clones exactos. Para clon exacto haría falta otro proveedor de imagen (pieza futura). La **imagen de referencia por escena** sí usa `images.edit` para recrear una foto concreta.
- **Audio de una sola síntesis** (no por escena): el guion se concatena y se manda completo a TTS; el vídeo se ajusta al audio (duraciones por proporción de palabras + Whisper). El final entrecortado se resolvió escribiendo la narración como prosa continua, no troceando el audio.
- **Outro con cola + fundidos** en vez de `-shortest`: cortar justo al acabar la voz se sentía amateur.
- **ffmpeg/ffprobe localizables sin PATH** (`ffmpeg_utils._resolve`): el `[WinError 2]` en la narración venía de que el servidor no tenía el ffmpeg de winget en el PATH.
- **Contraseña local = decisión diferida:** en el modelo self-hosted actual la contraseña es algo redundante (la licencia ya es la puerta y el server solo escucha en 127.0.0.1). Se decidió **dejarla como está** por ahora (no añadir código) y revisitar en Fase 2 (cuando la app se exponga en red/servidor compartido); la auth multi-cliente de la nube será un sistema aparte.
- **El modo Inventar NO verifica hechos** (puede alucinar / dejar placeholders) → por eso existe la revisión/edición antes de producir, y los modos con fuente real.
- **WhatsApp no sirve** para publicar en feed (su API es de mensajería).
- **Orden de integración real de redes:** YouTube (API más accesible) → Meta IG/FB (App en revisión) → TikTok (auditoría 2-6 semanas; antes solo posts privados). La base ya soporta los 4.
- **Las cuentas las posee/crea el usuario** en cada plataforma (Google Brand Accounts, Meta Business Manager, TikTok) y las conecta a cada **marca** en PressForge. PressForge no crea cuentas.
- **Una imagen bloqueada no debe tumbar el reel** → reintento + alternativa.
- **Windows/encoding:** se fuerza UTF-8 en stdout desde `pressforge/__init__.py` (rich rompía con cp1252).
- **Modelo de negocio = vender como software BYOK** (Bring Your Own Key): el cliente instala/corre la app y pone SU propia API key. Por eso las keys se gestionan en **Ajustes → API Keys** (UI), guardadas en `secrets.json` **local a cada equipo** (gitignored y FUERA de `STORAGE_DIR`/Drive — los secretos no se sincronizan ni viajan). `_openai_client.resolve_openai_key()`: secret de la UI → `.env` (respaldo dev).
  Para vender: ✅ (1) API keys en UI · ✅ (2) **login** (`auth.py`) · ✅ (3a) **licencias** (`licensing.py`: Ed25519 offline, la app lleva solo la PÚBLICA; sin licencia válida no se puede hacer login/setup). Pendiente (3b): instalador nativo (PyInstaller + ffmpeg) — opcional; los lanzadores `setup.command`/`run.command` (Mac) y `.bat` (Windows) ya hacen el arranque turnkey. SaaS (hosted, billing) sería proyecto aparte.
  - **Flujo de venta (licencias):** la clave privada está SOLO en `license_private_key.txt` (gitignored, la guarda el vendedor). Para emitir una licencia a un cliente: `python tools/make_license.py "Nombre" correo [exp YYYY-MM-DD]` → imprime la clave → el cliente la pega en la pantalla de activación. La pública está incrustada en `licensing.py`. Contraseña y licencia son **por equipo** (secrets.json local, no sincroniza).
  - **Visión de negocio en 2 fases (ver `docs/PLAN_VENTA.md`):** FASE 1 (ahora) = usar PressForge para los canales propios y hacerlos caso de éxito (NO se vende aún; la licencia offline + login bastan). FASE 2 (cuando el dueño decida lanzar) = vender por **suscripción mensual** con servidor propio en **Hetzner** (License Server + Stripe + panel admin + validación online con periodo de gracia; reemplaza la licencia offline). **Decisión: NO construir Fase 2 todavía** — primero validar con contenido. BYOK se mantiene (cada cliente su key de OpenAI).
- **Datos y reels portables entre PCs:** `data/` (marcas, cola, refs), `output/` (reels), `music/` y `branding/` están en `.gitignore` a propósito (no viajan por git), pero sí por **Google Drive**: `STORAGE_DIR` en `.env` (`config.py: data_path()/output_path()/music_path()/branding_path()`) apunta a la MISMA carpeta de Drive sincronizada en cada equipo → marcas, videos, música y brand kits se comparten solos. Vacío = carpeta del proyecto. Overrides finos: `DATA_DIR`, `OUTPUT_DIR`, `MUSIC_DIR`. **Excepción:** `secrets.json` (API keys, contraseña, licencia) es **local a cada equipo** y NO se sincroniza.

---

## 5. Estado y limitaciones actuales

- ✅ Todo el flujo crear → editar → producir → organizar por marca → programar/publicar (manual) funciona end-to-end y está probado.
- 🟡 **Publicación automática real**: aún es "manual asistido" (prepara `caption_<red>.txt` junto al reel + descarga del mp4). Falta implementar los `PublishProvider` reales por plataforma (OAuth + subida).
- 🟡 **Scheduler**: corre solo **con la app abierta** (`serve`). Para 24/7 sin la app, mover a un servicio/cron.
- ℹ️ **Costo por reel** (OpenAI, calidad `low`): ~$0.10–$0.40 según nº de imágenes. `IMAGE_QUALITY` en `.env`.
- ℹ️ Estado en memoria (jobs, guiones, candidatos) se pierde al reiniciar el server; lo persistente es `data/publish.json` y los archivos en `output/`.

---

## 6. Próximos pasos sugeridos (de mayor a menor impacto)

1. **YouTube real** (`PublishProvider`): OAuth 2.0 + YouTube Data API v3 para subir `reel.mp4` con título/descripción/tags. Requiere credenciales del usuario en Google Cloud Console. Registrar el provider en `publishing/scheduler.py` (`PUBLISHERS['youtube']`).
2. **Meta (Instagram Reels + Facebook)**: App de Meta + Business Manager + tokens; publicar vía Graph API. Reusa los campos de canal por marca.
3. **TikTok**: modo "Upload to Inbox" (semi-automático, evita la auditoría dura).
4. **Scheduler 24/7** sin la app abierta (servicio/cron del sistema, o cloud).
5. **Pulidos pendientes**: énfasis de subtítulos por palabra clave (que el guion marque las palabras), elegir fecha en Efemérides (no solo hoy), duración objetivo del reel, más pistas de música por mood (íbamos por la pista 6: oscuro/terror).

### Migración a local/gratis (V6) — estado
La arquitectura permite mezclar pago/local por `.env`. Análisis honesto de calidad:
- **Guion → Ollama** (`SCRIPT_PROVIDER=ollama`): YA construido (`providers/ollama_script.py`, subclase de OpenAIScriptProvider vía endpoint OpenAI-compat de Ollama). Default `qwen3:30b` (mejor que deepseek-r1 para esto: r1 "piensa" y rompe el JSON). **Falta probar/afinar en la Mac** (incl. desactivar el "thinking" de Qwen3 para JSON limpio). Calidad ~90% de GPT-4o.
- **Subtítulos → Whisper local** (whisper.cpp/faster-whisper en la M1): calidad **idéntica**, gratis. Pendiente crear el provider. Mejor primer win.
- **Imágenes → FLUX/SDXL local** (Draw Things/ComfyUI/mflux, NO Ollama): puede igualar a gpt-image-1, más setup/lento. Pendiente.
- **Voz → TTS local** (XTTS/F5, NO Ollama): lo más difícil de igualar gratis. Alternativa premium YA integrada: **ElevenLabs** (`providers/elevenlabs_voice.py`, `VOICE_PROVIDER=elevenlabs`, key en Ajustes/BYOK, `ELEVENLABS_VOICE_ID`/`ELEVENLABS_MODEL=eleven_multilingual_v2`) — voz muy natural en español, de pago por caracteres.
El usuario trabajará en una **Mac M1 Pro Max con Ollama** (modelos: qwen3:30b, deepseek-r1:32b/14b). Claude también estará en la Mac.

---

## 7. Cómo retomar con Claude en otra PC

1. Clona el repo y haz el **setup** (ver `README.md`). Recuerda recrear `.env` con tu `OPENAI_API_KEY` (no viaja en el repo) y, si quieres conservar marcas/cola, copiar la carpeta `data/`.
2. Abre Claude Code en la carpeta del proyecto y dile algo como:
   *"Lee `docs/CONTEXT.md` y el `README.md`; retomamos PressForge Studio desde donde quedó. Quiero seguir con [lo que sea]."*
3. La memoria de Claude es local de cada máquina, así que **este documento es la fuente de verdad** del contexto entre PCs. Si hacemos cambios grandes, lo actualizamos.
4. Para generar imágenes/logos/banners a la carta con Claude: ver **`docs/GENERAR_IMAGENES.md`** (modelo, tamaños, prompts que funcionan, script reutilizable y recorte por red).

---

## 8. Historial de hitos (git)

```
97117d8  Outro: cola tras la voz + fundido a negro + fundido de música
3bd7fdc  Entonación de cierre (última frase suena a final)
49ea0f9  Narración continua + personajes secundarios consistentes
204a401  Imagen de referencia por escena (recrear foto en el estilo)
62c485e  Personajes: control por escena (chips) + prohibir extras
ebb8903  Consistencia de personajes (biblia de personajes)
bd0196e  Brand kits en Drive + versionado por intento (acordeón)
356d06d  Marcas: cargar brand kit existente al abrir el editor
fc25ba7  Estilo visual 3D animado (Pixar/Disney)
c571a80  Estilos visuales seleccionables (cinematic/photo/vivid/…)
d8e5349  Voz ElevenLabs: control de velocidad
aabef2d  Curiosidades virales desde Reddit (RSS)
405c34c  Fix: localizar ffmpeg/ffprobe sin PATH (WinError 2)
e0ff047  Biblioteca de voces ElevenLabs + preview play/stop
(varios) Selector de voz/proveedor en Crear; sesiones persistentes; licencias
7b0a620  Robustez de imágenes ante el filtro de seguridad
bdb1c07  Marcas/Canales por nicho
e5fcce1  Sistema de publicación (base): editor, programación, agenda
6372ba3  Música: editar tags con lápiz; logo/favicon más visibles
06b89fb  Histórico/Efemérides: listar primero, elegir, luego generar
a267d04  Branding: logo + iconos outline
8978121  Fecha exacta en efemérides + guiones en acordeón
f3b3375  Imágenes auto-escaladas por longitud del guion
fcf20f1  UTF-8 desde __init__
e5e7bf0  Hooks más fuertes (doctrina del hook)
122f149  Modos Histórico y Qué pasó hoy (Wikipedia)
27419e3  Flujo de 2 pasos + UI tipo Suno + Mi guion
346078d  Fix subtítulos desbordados
2524f79  Commit inicial V1 (pipeline + Web + música)
```
