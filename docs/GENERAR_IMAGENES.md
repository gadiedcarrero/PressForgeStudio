# Generar imágenes con IA (logos, banners, escenas)

Guía del proceso que usamos para crear imágenes a mano (logos del canal, banners,
o imágenes sueltas) con la misma calidad que salieron las buenas. Sirve para
pedírselo a Claude en la Mac **o** para correrlo tú.

> El código "oficial" ya vive en el proyecto:
> - `pressforge/branding.py` → genera el **brand kit** (logo + banners por red)
> - `pressforge/providers/openai_image.py` → imágenes de **escena** de los reels
>
> Este documento es la **receta manual/ad-hoc** para generar imágenes a la carta.

---

## 1. El modelo y sus tamaños

Usamos **`gpt-image-1`** (OpenAI). Solo acepta 3 tamaños:

| Tamaño | Forma | Para qué |
|---|---|---|
| `1024x1024` | cuadrado | **logos / fotos de perfil** |
| `1536x1024` | horizontal | **banners / portadas** (luego se recortan) |
| `1024x1536` | vertical | **imágenes de escena** del reel (9:16) |

Calidad: `low` / `medium` / `high`. Para branding usamos **`high`**; para pruebas de reel, `low`/`medium`.

> ⚠️ No genera 16:9 ni medidas exactas de redes directamente → generamos `1536x1024` y **recortamos con FFmpeg** (ver §4).

---

## 2. La receta de prompts (lo que hizo que salieran bien)

**Regla de oro del LOGO** → *UN solo símbolo limpio*, no un collage:
> "Professional emblem logo inspired by {tema}. **ONE single bold iconic symbol**
> centered inside a circular golden badge, flat vector, thick clean lines,
> **generous negative space, simple and uncluttered (not a collage)**, gold-on-deep-dark,
> dramatic rim lighting, legible at tiny sizes, **no text, no letters, no watermark**."

**Regla de oro del BANNER** → cinematográfico + centro libre para el título:
> "Wide cinematic channel banner background about {tema}. Epic dramatic scene,
> **golden divine volumetric light rays**, atmospheric depth, fog and shadows,
> subtle silhouettes, premium cinematic color grading. **Keep a clear darker EMPTY
> space in the CENTER for a title.** Ultra-wide composition. **no text, no letters**."

**Imagen de ESCENA (reel)** → realismo histórico, sin texto, no gráfico:
> "{descripción de la escena}, cinematic historical realism, dramatic lighting,
> vertical 9:16, **no text, tasteful, no gore, no nudity, no explicit violence**."

Claves que marcaron la diferencia:
- **Logo = un símbolo**, mucho espacio negativo, "no text" (gpt-image-1 escribe mal el texto).
- **Dorado sobre fondo oscuro** = se ve premium.
- **Banner con centro vacío** para poner el nombre encima después.
- Siempre **"no text, no letters"** salvo que quieras que intente texto (suele salir mal).

---

## 3. Script reutilizable (genera imágenes sueltas)

Crea un archivo temporal (ej. `_img.py`) en la raíz del proyecto y córrelo con el venv.
Reutiliza el cliente de OpenAI del proyecto (lee tu `OPENAI_API_KEY` del `.env`):

```python
# _img.py
import base64
from pathlib import Path
from pressforge.providers._openai_client import client

OUT = Path("output/_imagenes"); OUT.mkdir(parents=True, exist_ok=True)

def gen(prompt, size, name, quality="high"):
    r = client().images.generate(model="gpt-image-1", prompt=prompt,
                                 size=size, quality=quality, n=1)
    p = OUT / name
    p.write_bytes(base64.b64decode(r.data[0].b64_json))
    print("OK ->", p)

# Ejemplos:
gen("Professional emblem logo ... no text", "1024x1024", "logo.png")
gen("Wide cinematic banner ... no text", "1536x1024", "banner.png")
```

Ejecuta:
```bash
.venv/bin/python _img.py        # macOS
# .\.venv\Scripts\python.exe _img.py   # Windows
```
Las imágenes quedan en `output/_imagenes/`. Borra `_img.py` al terminar.

---

## 4. Recortar a tamaños exactos de cada red (FFmpeg)

Desde una base `1536x1024`, recorta/escala al tamaño exacto (rellena y centra):

```bash
ffmpeg -y -i banner.png -vf "scale=2048:1152:force_original_aspect_ratio=increase,crop=2048:1152" youtube.png
```

Tamaños útiles:
| Red | WxH |
|---|---|
| YouTube banner | 2048×1152 |
| Facebook portada | 1640×856 |
| X/Twitter cabecera | 1500×500 |
| Instagram post | 1080×1080 |

(Esto es justo lo que hace `pressforge/branding.py` automáticamente.)

---

## 5. Cómo pedírmelo a Claude (en la Mac)

Solo dime el qué y el estilo, p. ej.:
> *"Genérame 2 logos para el canal 'X' sobre {tema}, estilo dorado minimalista, un solo símbolo."*
> *"Hazme un banner de YouTube para {tema}, cinematográfico, con centro libre para el título."*

Yo escribo el script temporal, lo ejecuto, **te muestro las imágenes**, y si no te gustan, ajusto el prompt y regenero hasta que queden. (Tú apruebas antes de usarlas.)

---

## 6. Costo
`gpt-image-1` en `high` ≈ **$0.10–$0.17 por imagen** (en `low`/`medium` mucho menos).
Un brand kit completo (2 logos + 1 banner base) ≈ **$0.40–$0.50**, una vez por marca.
