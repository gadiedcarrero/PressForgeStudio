"""ScriptProvider basado en OpenAI con salida estructurada.

Genera en una sola llamada: idea viral + guion optimizado para retención +
storyboard (cada escena con su prompt de imagen). Mantener todo en una llamada
da coherencia visual y narrativa entre escenas.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import get_settings
from ..models import Character, Scene, SourceFact, Story, StoryDraft
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
concreta (un lugar, un objeto, un símbolo), déjala vacía.

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

Recibes un DIÁLOGO entre personajes (las líneas suelen venir atribuidas: 'ELLA:', \
'ÉL:', un nombre, etc.). Tu trabajo es convertirlo en un storyboard de diálogo.

REGLAS DE ORO:
- NO inventes diálogo nuevo ni cambies lo que dicen. Usa SUS líneas tal cual \
(solo corrige ortografía/puntuación mínima). No añadas líneas que no existan.
- Identifica a los personajes que hablan. En `characters`, crea una entrada por \
cada uno con su descripción VISUAL fija EN INGLÉS (edad, género, etnia/piel, pelo, \
complexión, ropa, rasgos) para que salgan IGUALES en todas las escenas. Usa como \
nombre el que aparece en el guion (p. ej. 'Ella', 'Él', o el nombre propio).
- Divide el diálogo en escenas: normalmente UNA escena por línea/turno de habla. \
En CADA escena rellena:
  · `speaker`: el personaje (de tu lista) que DICE esa línea.
  · `narration`: esa línea, lo que dice (tal cual).
  · `image_prompt` EN INGLÉS: la escena concreta de lo que ocurre — el que habla \
hablando con la emoción adecuada Y el OTRO personaje reaccionando de forma \
coherente con el contexto (asiente, usa el móvil, escribe, protesta, se sorprende…). \
Incluye a ambos en cuadro si están presentes. Coherencia de lugar/vestuario/paleta.
  · `characters`: quiénes aparecen en esa escena.
- `hook` = la primera línea; `cta` = la última línea (NO las reescribas como \
pattern-interrupt: es un diálogo, mantén su naturalidad).
- Sugiere `music_mood` acorde al tono de la conversación.""" + _CHARACTER_DOCTRINE


class OpenAIScriptProvider:
    def __init__(self, client_obj=None, model: str | None = None) -> None:
        self.settings = get_settings()
        # Parametrizable para reutilizar toda la lógica con otro motor (Ollama).
        self._client = client_obj or client()
        self._model = model or self.settings.script_model

    def generate(self, niche: str, *, scenes: int, extra: str | None = None,
                 target_words: int | None = None) -> Story:
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
                {"role": "system", "content": _SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.9,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")

        return self._to_story(draft, niche=niche)

    def refine(self, user_script: str, *, scenes: int, extra: str | None = None) -> Story:
        """Modo 'Mi guion': pule el texto del usuario sin inventar hechos."""
        user = (
            f"Guion del usuario:\n\"\"\"\n{user_script.strip()}\n\"\"\"\n\n"
            f"Optimízalo y divídelo en ~{scenes} escenas cortas "
            f"(~10-14 palabras cada una, para que la imagen cambie cada 3-5 s; "
            f"la 1ª es el hook, la última el cierre).\n"
        )
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _REFINE_SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.4,  # más fiel al original que en modo inventar
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")
        return self._to_story(draft, niche="Mi guion")

    def dialogue(self, user_script: str, *, extra: str | None = None) -> Story:
        """Modo Diálogo (solo 'Mi guion'): convierte un diálogo atribuido en un
        storyboard con speaker por escena, sin inventar lo que dicen."""
        user = (
            f"DIÁLOGO del usuario (respeta lo que dice cada quien):\n"
            f"\"\"\"\n{user_script.strip()}\n\"\"\"\n\n"
            f"Conviértelo en escenas (una por turno de habla), con speaker, su "
            f"línea y la descripción visual de la escena.\n"
        )
        if extra:
            user += f"Indicaciones extra: {extra}\n"
        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _DIALOGUE_SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.3,  # fiel al diálogo del usuario
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un diálogo válido.")
        return self._to_story(draft, niche="Diálogo")

    def from_source(self, fact: SourceFact, *, scenes: int, extra: str | None = None,
                    target_words: int | None = None) -> Story:
        """Modos Histórico / Qué pasó hoy / Reddit: guion fiel a hechos reales."""
        year = f" (año {fact.year})" if fact.year else ""
        user = (
            f"Tema/título: {fact.title}{year}\n\n"
            f"HECHOS REALES (fuente):\n\"\"\"\n{fact.extract.strip()}\n\"\"\"\n\n"
            f"Escribe el guion en ~{scenes} escenas cortas (~10-14 palabras "
            f"cada una, imagen cada 3-5 s), fiel a estos hechos.\n"
        )
        user += _length_hint(target_words)
        if extra:
            user += f"Indicaciones extra: {extra}\n"

        completion = self._client.beta.chat.completions.parse(
            model=self._model,
            messages=[
                {"role": "system", "content": _SOURCE_SYSTEM.format(language=self.settings.language)},
                {"role": "user", "content": user},
            ],
            response_format=StoryDraft,
            temperature=0.5,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("El modelo no devolvió un guion válido.")
        story = self._to_story(draft, niche=fact.title)
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
