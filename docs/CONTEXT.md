# PressForge Studio — Contexto del proyecto

> Documento para **retomar el proyecto desde cualquier PC** (y para que Claude
> recupere contexto). Resume qué es, cómo está construido, las decisiones
> tomadas, el estado actual y los próximos pasos. Última actualización tras el
> commit `7b0a620`.

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

- **Backend/pipeline:** Python. **Web:** FastAPI + una sola `index.html` (Tailwind por CDN, dark mode, estilo "Suno" con sidebar). **Render:** FFmpeg. **IA:** OpenAI (guion `gpt-4o`, imágenes `gpt-image-1`, voz `gpt-4o-mini-tts`, subtítulos `whisper-1`). **Fuente histórica:** Wikipedia/Wikimedia REST (sin API key).
- **Providers desacoplados** (`pressforge/providers/base.py`, `Protocol`s) seleccionables por env vars en `registry.py`: Script, Image, Voice, Subtitle, Render, Music, Research. Mañana se cambia cualquiera a modelo local sin tocar el pipeline.
- **Flujo de 2 pasos:** `generate_stories(mode,…)` → guion(es) editables → `produce_reel(story,…)` (imágenes/voz/subs/render). En la web son `/api/scripts` y `/api/produce`.
- **Publicación** (`pressforge/publishing/`): store en `data/publish.json`, publicador `manual`, `scheduler` en hilo de fondo. Un `PublishProvider` por red (hoy todos manuales).

### Mapa de archivos clave
- `pipeline.py` — `generate_stories`, `generate_story`, `generate_story_from_fact`, `produce_reel`, `generate_reel` (CLI), `auto_scene_count`, `human_date`, `_fallback_image`.
- `providers/openai_script.py` — `generate` (inventar), `refine` (mi guion), `from_source` (Wikipedia), `select_events` (efemérides). Incluye `_HOOK_DOCTRINE` (hook fuerte) inyectada en los 3 prompts.
- `providers/openai_image.py` — gpt-image-1 con **reintento suavizado** y `ImageBlockedError`.
- `providers/wikipedia_research.py` — `search(tema)` y `on_this_day(mm,dd)`. Tiene fallback TLS (reloj del sistema desfasado).
- `subtitles.py` — ASS estilo TikTok, **wrap a 2 líneas** según ancho del frame.
- `music_library.py` — tags en `assets/music/library.json`, matching ponderado por mood.
- `publishing/store.py` — posts, cola, **marcas** (CRUD), reel→marca, `channels_for_reel`.
- `web/app.py` — toda la API. `web/index.html` — toda la UI (vistas: Crear, Library, Música, Agenda, Marcas + modal genérico).

---

## 3. Funcionalidades implementadas

- **Crear** (4 modos): Inventar · Mi guion · Histórico (Wikipedia) · Qué pasó hoy (efemérides). Histórico/Efemérides **listan primero** los resultados y el usuario **elige cuáles** convertir en guion (no se gasta IA en lo que no interesa). Variantes (1-3) en Inventar.
- **Guion editable** (acordeón si hay varios): título, hook, escenas (narración + prompt de imagen), CTA, fecha y fuente citada. **Hook fuerte** garantizado por la doctrina del hook.
- **Producción:** nº de imágenes **auto-escalado** por longitud (~1 cada 4 s, tope 18). Subtítulos sin desbordarse. Resiliencia ante el filtro de seguridad de imágenes (reintento → reutiliza anterior → neutral → sólido).
- **Música:** subir + tags (lápiz para editar con sugerencias), selección `Auto` por mood.
- **Marcas/Canales:** una marca por nicho con nicho, hashtags/voz/música por defecto y cuentas por plataforma. Reels se asignan a marca (hereda estilo); Library tiene badge y filtro por marca.
- **Publicación:** editor de reel (caption auto-sugerido + hashtags + plataformas), **publicar ahora** (manual asistido) y **programar** (individual o en lote: N reels, 1/día). **Agenda** con estado. Scheduler en hilo de fondo. Descarga con el **título** del vídeo (`/api/reels/{id}/download`).
- **Internal linking:** botón "Generar con IA" en el editor → descripción + hashtags + **entidades clave** (`describe()` en el ScriptProvider). `/api/reels/{id}/related` cruza esas entidades con otros reels (substring sobre su story.json) para sugerir **reels relacionados** e insertar referencias en el caption (telaraña Medusa→Poseidón→…).
- **Branding:** logo isotipo + favicon; iconos SVG outline monocromos.

---

## 4. Decisiones importantes (el "por qué")

- **No scrapear Quora/Reddit** para historia real → **Wikipedia/Wikimedia API** (oficial, gratis, citable). El endpoint "On this day" da efemérides reales por fecha.
- **El modo Inventar NO verifica hechos** (puede alucinar / dejar placeholders) → por eso existe la revisión/edición antes de producir, y los modos con fuente real.
- **WhatsApp no sirve** para publicar en feed (su API es de mensajería).
- **Orden de integración real de redes:** YouTube (API más accesible) → Meta IG/FB (App en revisión) → TikTok (auditoría 2-6 semanas; antes solo posts privados). La base ya soporta los 4.
- **Las cuentas las posee/crea el usuario** en cada plataforma (Google Brand Accounts, Meta Business Manager, TikTok) y las conecta a cada **marca** en PressForge. PressForge no crea cuentas.
- **Una imagen bloqueada no debe tumbar el reel** → reintento + alternativa.
- **Windows/encoding:** se fuerza UTF-8 en stdout desde `pressforge/__init__.py` (rich rompía con cp1252).

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

---

## 7. Cómo retomar con Claude en otra PC

1. Clona el repo y haz el **setup** (ver `README.md`). Recuerda recrear `.env` con tu `OPENAI_API_KEY` (no viaja en el repo) y, si quieres conservar marcas/cola, copiar la carpeta `data/`.
2. Abre Claude Code en la carpeta del proyecto y dile algo como:
   *"Lee `docs/CONTEXT.md` y el `README.md`; retomamos PressForge Studio desde donde quedó. Quiero seguir con [lo que sea]."*
3. La memoria de Claude es local de cada máquina, así que **este documento es la fuente de verdad** del contexto entre PCs. Si hacemos cambios grandes, lo actualizamos.

---

## 8. Historial de hitos (git)

```
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
