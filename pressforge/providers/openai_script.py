"""ScriptProvider basado en OpenAI con salida estructurada.

Genera en una sola llamada: idea viral + guion optimizado para retención +
storyboard (cada escena con su prompt de imagen). Mantener todo en una llamada
da coherencia visual y narrativa entre escenas.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import get_settings
from ..models import Character, DialogueDraft, Scene, SourceFact, Story, StoryDraft
from ._openai_client import client


def _length_hint(target_words: int | None) -> str:
    """Instrucción de longitud según las palabras objetivo (≈2.6 pal/s en es)."""
    if not target_words:
        return ""
    secs = round(target_words / 2.4)
    return (f"DURACIÓN OBJETIVO: ~{target_words} palabras en total de narración "
            f"(≈{secs}s de voz). Reparte esas palabras entre las escenas.\n")


class _EventSelection(BaseModel):
    indices: list[int] = Field(
        description="Índices (0-based) de los eventos elegidos, en orden de "
        "interés viral, los que mejor encajen con el tema pedido."
    )


class _Description(BaseModel):
    caption: str = Field(
        description="Descripción/caption del reel para redes (2-4 líneas), con "
        "gancho, que invite a ver y comentar. SIN hashtags dentro del texto."
    )
    hashtags: list[str] = Field(description="5-8 hashtags relevantes, SIN el símbolo #.")
    entities: list[str] = Field(
        description="3-8 entidades clave mencionadas en la historia (personajes, "
        "dioses, lugares, eventos, civilizaciones) que podrían ser su PROPIO "
        "reel. Nombres propios, sin artículos. Ej: 'Poseidón', 'Atenea'."
    )


# Inyectada en TODOS los prompts de guion. El hook es ~50% del éxito del reel.
_HOOK_DOCTRINE = """

═══ DOCTRINA DEL HOOK (lo más importante de todo) ═══
La narración de la PRIMERA escena ES el hook: lo primero que se oye y se lee
(0-3 s). Debe ser un "pattern interrupt" que rompa el scroll y abra un bucle de
curiosidad que OBLIGUE a quedarse. El hook decide si el algoritmo muestra el
vídeo o no.

PROHIBIDO empezar lento o con contexto/fecha/preámbulo. Nada de:
"Era el año…", "En julio de 1945…", "Había una vez…", "Esta es la historia
de…", "Muy triste.". Esos arranques pierden a la gente en el segundo 2.

Empieza por lo MÁS impactante, raro o contradictorio. El quién/cuándo/dónde va
DESPUÉS, en las siguientes escenas. El hook debe provocar "espera… ¿qué?".

Técnicas (elige la que mejor encaje con la historia):
- Brecha de curiosidad: "La historia detrás de esta foto es peor de lo que imaginas."
- Shock / contradicción: "No era nieve." · "La cosa blanca con la que jugaban era radiactiva."
- Todos menos uno: "Todas las niñas de esta foto murieron jóvenes… excepto una."
- In media res (acción ya empezada): "Unas niñas nadaban en un río cuando el cielo cambió de golpe."
- Pregunta que abre bucle: "¿Por qué estas niñas jugaron con polvo nuclear creyendo que era nieve?"

Comparación real:
✗ MALO (lento):  "Muy triste. En julio de 1945, un grupo de niñas fue de campamento…"
✓ BUENO (hook):  "Estas niñas pensaron que jugaban con nieve… pero era polvo de una bomba nuclear."

El campo `hook` y la narración de la escena 1 deben COINCIDIR: ambos son ese
pattern interrupt. Mantén el resto de escenas con ritmo alto y un cierre con payoff."""


# Inyectada en los prompts que generan storyboard. Resuelve que cada imagen
# saque a la MISMA persona y que el prompt no se desligue del sujeto real.
_CHARACTER_DOCTRINE = """

═══ CONSISTENCIA DE PERSONAJES (misma cara, cuerpo/ropa variables) ═══
Antes de escribir las escenas, LEE toda la historia e identifica a las personas
concretas que aparecen (protagonista y secundarios recurrentes). Para cada una
rellena `characters` con su IDENTIDAD FIJA EN INGLÉS: rostro y rasgos faciales,
ojos, etnia/tono de piel, color y estilo de pelo, edad, género. Eso se repite en
cada imagen para mantener la MISMA CARA.
IMPORTANTE: la `description` del personaje NO lleva ropa ni complexión/cuerpo,
porque ESO PUEDE CAMBIAR entre escenas (alguien adelgaza, engorda, se vuelve
musculoso, se cambia de ropa, un makeover…). El vestuario y el cuerpo de cada
momento van en el `image_prompt` de la escena correspondiente. Si la historia
implica un cambio (de ropa o físico), refléjalo en el image_prompt de esa escena
y en adelante, manteniendo SIEMPRE la misma cara.

Luego, en CADA escena, rellena `characters` con los nombres (exactos, de tu
lista) de quienes aparecen en esa escena. Si la escena no muestra a una persona
concreta (un lugar, un objeto, un símbolo), déjala vacía Y en su `image_prompt`
escribe explícitamente que NO hay personas (añade "no people, empty of humans, no
figures"). NUNCA dejes que la imagen invente a un desconocido al azar: una escena
simbólica de la mujer protagonista no puede acabar mostrando a un hombre joven.

═══ ÉPOCA Y VESTUARIO (deben coincidir con el tiempo real de la historia) ═══
Fija el PERIODO concreto de la historia (la década o el año aproximado en que
ocurre cada momento) y mételo en CADA `image_prompt`: por ejemplo "1890s",
"early 1900s", "1840s". El vestuario, peinado, objetos y arquitectura deben
corresponder a ESE periodo —no a otro siglo— y a la EDAD del personaje en ese
momento (si la historia abarca su juventud y su vejez, la ropa y la edad cambian
en consecuencia, pero la época nunca se desfasa). Nada de prendas o tecnología
de un siglo equivocado.

Incluye a TODAS las personas que reaparecen: el protagonista Y los secundarios
(p. ej. el acusador, la víctima, el juez, el padre…), no solo al principal. Si
la MISMA persona aparece en distintas etapas de su vida (de adolescente a
adulta), es UN SOLO personaje: mantén su identidad (rostro, etnia, rasgos, pelo)
y, si acaso, solo ajusta la edad. Etiquétala en TODAS las escenas donde aparezca,
aunque la narración solo la mencione de pasada.

CADA `image_prompt` debe mostrar el SUJETO REAL de su narración, nunca algo
genérico/simbólico desligado del tema. Si la narración habla de una persona
concreta, la imagen es ESA persona (usando su descripción), no un desconocido al
azar. Mantén coherencia de época, vestuario y paleta en todo el reel."""


# Inyectada en los prompts de guion. La voz narra UNA historia de corrido.
_NARRATION_DOCTRINE = """

═══ NARRACIÓN CONTINUA (una sola voz, sin tirones) ═══
El audio se genera de UNA sola vez y la voz cuenta UNA historia fluida de
principio a fin. Al concatenar las narraciones de todas las escenas EN ORDEN
debe leerse como un texto natural y continuo —como un narrador contando la
historia de corrido—, NO como una lista de frases cortas, secas e inconexas.
- Usa conectores y transiciones naturales (y, pero, entonces, sin embargo, años
  después, lo que nadie esperaba…). VARÍA la longitud de las frases.
- Una escena es un CORTE VISUAL, no obligatoriamente una frase completa: una
  misma frase puede repartirse entre dos escenas si el sentido continúa.
- Evita el efecto "robot" de sujeto-verbo-punto repetido. Que respire como prosa
  real. Las imágenes se ajustan luego a ese audio continuo.

CIERRE con entonación final: la narración de la ÚLTIMA escena (y el campo `cta`)
debe ser una frase CONCLUSIVA y COMPLETA que suene a final —como cuando alguien
cierra y baja el tono para indicar que ya no hay más—. Una afirmación rotunda o
una reflexión que cierra el círculo, terminada en punto firme (o '?'/'!'). NUNCA
termines con conectores ni con algo que insinúe continuación (y…, pero…, "lo que
nadie sabe es…", "entonces…"). Debe quedar claro que ahí ACABA la historia."""


_SYSTEM = """Eres un guionista experto en contenido viral histórico para reels \
verticales (TikTok/Reels/Shorts). Escribes en {language}.

Tu trabajo: a partir de un nicho, inventar UNA historia real e impactante y \
convertirla en un guion de documental corto (30-60s) optimizado para retención.

Reglas del guion:
- HOOK (escena 1): 0-3s, curiosidad extrema. Ej: "Este rey murió de una forma \
tan absurda que parece inventada."
- DESARROLLO: explicación rápida, lenguaje sencillo, sin relleno, ritmo alto.
- CIERRE (última escena): payoff sorprendente. Ej: "Y sí, esto quedó \
registrado en la historia."
- Longitud: ajusta el total de palabras a la duración objetivo indicada.
- Prioriza rareza, shock, ironía y finales inesperados. Nada aburrido.
- Debe ser históricamente plausible/real, no inventado como falso.

Reglas de los image_prompt (en INGLÉS):
- Estilo "cinematic historical realism", iluminación dramática, 9:16 vertical.
- Coherencia visual entre escenas (misma época, paleta, calidad).
- Describe la escena concreta, sin texto ni letras en la imagen, sin marcas \
modernas si la época no corresponde.
- No gráfico: nada de gore, sangre, desnudez ni violencia explícita. Sugiere el \
drama con atmósfera, sombras, siluetas y expresión (evita disparar filtros).""" + _HOOK_DOCTRINE + _CHARACTER_DOCTRINE + _NARRATION_DOCTRINE

_REFINE_SYSTEM = """Eres un editor de guiones para reels históricos verticales \
(TikTok/Reels/Shorts). Escribes en {language}.

Recibes el guion que ESCRIBIÓ EL USUARIO. Tu trabajo es PULIRLO, no reescribir \
la historia:
- NO inventes hechos, fechas, nombres ni datos nuevos. Respeta el contenido del \
usuario. Si algo es ambiguo, mantenlo, no lo rellenes con invención.
- Mejora redacción, claridad y ritmo. Hazlo conciso, sin relleno.
- Convierte el inicio en un HOOK potente (0-3s) usando SOLO lo que el usuario \
aporta.
- Asegura un cierre con payoff.
- Divide el guion en escenas (la 1ª es el hook, la última el cierre).
- Crea un image_prompt en INGLÉS por escena: "cinematic historical realism", \
9:16 vertical, sin texto en la imagen, coherente entre escenas.
- Sugiere music_mood acorde al tono del guion del usuario.
- IMPORTANTE: aunque el usuario empiece lento, REESCRIBE el arranque como un \
hook potente usando el dato más fuerte que ÉL aporta (no inventes datos \
nuevos).""" + _HOOK_DOCTRINE + _CHARACTER_DOCTRINE + _NARRATION_DOCTRINE

_SOURCE_SYSTEM = """Eres un guionista de reels históricos virales. Escribes en \
{language}.

Recibes HECHOS REALES extraídos de Wikipedia sobre un tema. Conviértelos en un \
guion de documental corto (30-60s) optimizado para retención.

REGLA DE ORO — fidelidad a los hechos:
- Usa SOLO la información de los hechos dados. NO inventes fechas, nombres, \
cifras, causas ni citas que no aparezcan.
- Puedes simplificar, dramatizar el TONO y elegir el ángulo más curioso, pero \
sin falsear nada. Si un dato no está, no lo afirmes.
- Si los hechos son escasos, haz un guion más corto antes que rellenar con \
invención.

Formato: hook potente (0-3s) basado en el dato más sorprendente; desarrollo \
ágil y claro; cierre con payoff. Ajusta el total de palabras a la duración \
objetivo indicada (la 1ª escena es el hook, la última el cierre).
Si la fuente da para poco y piden un guion largo, NO rellenes con paja: añade \
solo contexto/consecuencias REALES que soporte la fuente, o quédate más corto.

image_prompt en INGLÉS por escena: "cinematic historical realism", 9:16 \
vertical, sin texto en la imagen, coherente y fiel a la época real del hecho. \
No gráfico (sin gore, sangre, desnudez ni violencia explícita): sugiere el \
drama con atmósfera y sombras.
Sugiere music_mood acorde.""" + _HOOK_DOCTRINE + _CHARACTER_DOCTRINE + _NARRATION_DOCTRINE


_DIALOGUE_SYSTEM = """Eres un director de animación para reels verticales. Escribes \
en {language}.

Recibes un GUION/DIÁLOGO (puede traer acotaciones de escena y líneas de diálogo \
atribuidas, estilo guion de cine). Lo conviertes en una secuencia de `beats`.

REGLAS DE ORO (críticas):
1. SOLO se HABLA el diálogo. Las acotaciones/acciones ("Un auto se detiene", \
"Víctor se mira confundido", "EXT. CASA - NOCHE") NUNCA se narran ni se dicen: se \
convierten en lo que se VE (van en `image_prompt`), NO en `line`.
2. `line` = las palabras EXACTAS que dice el personaje, VERBATIM del guion. NO \
parafrasees, NO uses tercera persona, NO digas "Víctor pregunta…". Si el guion dice \
'VÍCTOR: ¿Qué pasó?', entonces speaker='Víctor', line='¿Qué pasó?'.
3. Un beat por cada línea de diálogo. Si hay una acción importante sin diálogo, \
crea un beat con speaker y line VACÍOS y descríbela en `image_prompt`.
4. Personajes: en `characters`, una entrada por cada uno con su IDENTIDAD FIJA EN \
INGLÉS (cara, etnia/piel, ojos, pelo, edad). MISMA etnia y cara en TODO el video. \
SIN ropa ni cuerpo en la identidad (esos cambian). Asigna también a cada uno un \
`voice_style` distintivo EN INGLÉS (edad/género/tono) para que su VOZ sea la MISMA \
en todos los clips (ej. 'a warm deep adult male voice' / 'a bright young female voice').
5. VESTUARIO/ESTADO ACUMULATIVO: lee TODO el guion y lleva la cuenta del aspecto de \
cada personaje. Cuando algo cambia (pantalón negro, camisa blanca, saco…), ese \
cambio se MANTIENE en el `image_prompt` de esa escena y de TODAS las siguientes. \
Describe en cada `image_prompt` el atuendo COMPLETO ACTUAL de cada personaje visible.
6. ENCUADRE: plano AMPLIO / cuerpo entero que muestre la escena completa y el \
escenario, no solo de pecho para arriba (salvo que el momento pida primer plano).
7. El que HABLA mira a cámara / de frente, con la boca en gesto de hablar. El que \
ESCUCHA aparece de perfil o de tres cuartos, con la BOCA CERRADA, reaccionando con \
gestos del cuerpo (asiente, se cruza de brazos, usa el móvil…) — NUNCA con la boca \
abierta como si hablara (así solo se anima al que habla). `music_mood` acorde.""" + _CHARACTER_DOCTRINE


class OpenAIScriptProvider:
    def __init__(self, client_obj=None, model: str | None = None) -> None:
        self.settings = get_settings()
        # Parametrizable para reutilizar toda la lógica con otro motor (Ollama).
        self._client = client_obj or client()
        self._model = model or self.settings.script_model

    def generate(self, niche: str, *, scenes: int, extra: str | None = None,
                 target_words: int | None = None, language: str | None = None) -> Story:
        lang = language or self.settings.language
        user = (
            f"Nicho: {niche}\n"
            f"Apunta a ~{scenes} escenas (la 1ª es el hook, la última el cierre). "
            f"Cada escena = una idea corta (~10-14 palabras) para que la imagen "
            f"cambie cada 3-5 s; ajusta el número según la longitud real.\n"
        )
        user += _length_hint(target_words)
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM.format(language=lang)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.9,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")

        story = self._to_story(draft, niche=niche)
        story.language = lang
        return story

    def refine(self, user_script: str, *, scenes: int, extra: str | None = None,
               language: str | None = None) -> Story:
        """Modo 'Mi guion': pule el texto del usuario sin inventar hechos."""
        lang = language or self.settings.language
        user = (
            f"Guion del usuario:\n\"\"\"\n{user_script.strip()}\n\"\"\"\n\n"
            f"Optimízalo y divídelo en ~{scenes} escenas cortas "
            f"(~10-14 palabras cada una, para que la imagen cambie cada 3-5 s; "
            f"la 1ª es el hook, la última el cierre). Escribe la narración en {lang}.\n"
        )
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _REFINE_SYSTEM.format(language=lang)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.4,  # más fiel al original que en modo inventar
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")
        story = self._to_story(draft, niche="Mi guion")
        story.language = lang
        return story

    def dialogue(self, user_script: str, *, extra: str | None = None,
                 language: str | None = None) -> Story:
        """Modo Diálogo (solo 'Mi guion'): convierte un guion con acotaciones +
        líneas en beats (speaker + línea VERBATIM + escena), sin narrar acciones."""
        lang = language or self.settings.language
        user = (
            f"GUION del usuario (respeta LITERALMENTE lo que dice cada quien; las "
            f"acotaciones van a la imagen, no se dicen). Las líneas de diálogo deben "
            f"quedar en {lang} (tradúcelas si vienen en otro idioma, manteniendo el "
            f"sentido):\n\"\"\"\n{user_script.strip()}\n\"\"\"\n"
        )
        if extra:
            user += f"\nIndicaciones extra: {extra}\n"
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _DIALOGUE_SYSTEM.format(language=lang)},
                {"role": "user", "content": user},
            ],
            response_format=DialogueDraft,
            temperature=0.2,  # muy fiel al guion del usuario
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un diálogo válido.")
        story = self._dialogue_to_story(draft)
        story.language = lang
        return story

    @staticmethod
    def _dialogue_to_story(draft: "DialogueDraft") -> Story:
        characters = [
            Character(name=c.name.strip(), description=c.description.strip(),
                      voice_style=(c.voice_style or "").strip())
            for c in (draft.characters or []) if c.name.strip() and c.description.strip()
        ]
        names = [c.name for c in characters]
        valid = set(names)
        scenes: list[Scene] = []
        pending = ""  # acción sin diálogo → se antepone a la siguiente línea hablada
        for b in draft.beats:
            spk = (b.speaker or "").strip()
            line = (b.line or "").strip()
            img = (b.image_prompt or "").strip()
            if not spk or not line:  # beat de acción → acumular su visual
                pending = (pending + " " + img).strip()
                continue
            full_img = (pending + " " + img).strip() if pending else img
            pending = ""
            scenes.append(Scene(
                index=len(scenes), narration=line, image_prompt=full_img,
                characters=names[:], speaker=(spk if spk in valid else (names[0] if names else "")),
            ))
        # acción final sobrante → se añade al último plano
        if pending and scenes:
            scenes[-1].image_prompt = (scenes[-1].image_prompt + " " + pending).strip()
        if not scenes:
            raise RuntimeError("No detecté líneas de diálogo en el guion.")
        return Story(
            niche="Diálogo", title=draft.title or "Diálogo",
            hook=scenes[0].narration, cta=scenes[-1].narration,
            music_mood=draft.music_mood or "", characters=characters, scenes=scenes,
        )

    def from_source(self, fact: SourceFact, *, scenes: int, extra: str | None = None,
                    target_words: int | None = None, language: str | None = None) -> Story:
        """Modos Histórico / Qué pasó hoy / Reddit: guion fiel a hechos reales."""
        lang = language or self.settings.language
        year = f" (año {fact.year})" if fact.year else ""
        user = (
            f"Tema/título: {fact.title}{year}\n\n"
            f"HECHOS REALES (fuente):\n\"\"\"\n{fact.extract.strip()}\n\"\"\"\n\n"
            f"Escribe el guion en ~{scenes} escenas cortas (~10-14 palabras "
            f"cada una, imagen cada 3-5 s), fiel a estos hechos. Narración en {lang}.\n"
        )
        user += _length_hint(target_words)
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _SOURCE_SYSTEM.format(language=lang)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.5,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")
        story = self._to_story(draft, niche=fact.title)
        story.language = lang
        story.source_title = fact.title
        story.source_url = fact.url
        return story

    def select_events(self, events: list[SourceFact], theme: str, count: int) -> list[int]:
        """Elige los índices de los eventos que mejor encajan con el tema."""
        if not events:
            return []
        listing = "\n".join(
            f"{i}. ({e.year}) {e.extract}" for i, e in enumerate(events)
        )
        user = (
            f"Tema deseado: {theme or 'cualquiera, los más virales'}\n\n"
            f"Eventos reales de un día como hoy:\n{listing}\n\n"
            f"Elige los {count} más interesantes/virales que encajen con el tema."
        )
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": "Seleccionas eventos históricos para reels virales."},
                {"role": "user", "content": user},
            ],
            response_format=_EventSelection,
            temperature=0.3,
        )
        parsed = completion.choices[0].message.parsed
        idxs = parsed.indices if parsed else []
        # saneo: dentro de rango, sin duplicados, máximo count
        seen, clean = set(), []
        for i in idxs:
            if 0 <= i < len(events) and i not in seen:
                seen.add(i)
                clean.append(i)
            if len(clean) >= count:
                break
        return clean or list(range(min(count, len(events))))

    def describe(self, *, title: str, narration: str) -> dict:
        """Descripción para redes + hashtags + entidades clave (para enlazar reels)."""
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": (
                    f"Eres community manager de un canal de reels históricos. Escribes en "
                    f"{self.settings.language}. Generas la descripción para publicar el reel."
                )},
                {"role": "user", "content": f"Título: {title}\n\nNarración:\n{narration}"},
            ],
            response_format=_Description,
            temperature=0.6,
        )
        d = completion.choices[0].message.parsed
        if d is None:
            raise RuntimeError("No se pudo generar la descripción.")
        return {
            "caption": d.caption.strip(),
            "hashtags": [h.lstrip("#").strip() for h in d.hashtags if h.strip()],
            "entities": [e.strip() for e in d.entities if e.strip()],
        }

    @staticmethod
    def _to_story(draft: StoryDraft, *, niche: str) -> Story:
        characters = [
            Character(name=c.name.strip(), description=c.description.strip())
            for c in (draft.characters or []) if c.name.strip() and c.description.strip()
        ]
        valid = {c.name for c in characters}
        return Story(
            niche=niche,
            title=draft.title,
            hook=draft.hook,
            cta=draft.cta,
            music_mood=draft.music_mood,
            characters=characters,
            scenes=[
                Scene(
                    index=i, narration=s.narration, image_prompt=s.image_prompt,
                    characters=[n for n in (s.characters or []) if n in valid],
                    speaker=(s.speaker if s.speaker in valid else ""),
                )
                for i, s in enumerate(draft.scenes)
            ],
        )
