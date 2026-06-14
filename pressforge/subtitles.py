"""Genera un archivo .ass con subtítulos estilo TikTok a partir de las palabras
con timestamps (Word). Letras grandes, mayúsculas, alto contraste y la palabra
más fuerte de cada grupo resaltada en amarillo.

Clave anti-desbordamiento: cada subtítulo se envuelve manualmente en líneas que
caben en el ancho útil del frame (con `\\N`), estimando el ancho del texto a
partir del tamaño de fuente. Así nunca se sale por los lados.

ASS da control total de estilo y se quema en el vídeo con el filtro `ass` de
FFmpeg.
"""
from __future__ import annotations

from pathlib import Path

from .models import Word

# Cuántas palabras por subtítulo y separación máxima antes de cortar grupo.
_MAX_WORDS = 3
_MAX_GAP = 0.6  # segundos

# Ancho medio de carácter en Arial Black como fracción del tamaño de fuente.
# Conservador (ancho) para no quedarnos cortos al estimar.
_CHAR_W_RATIO = 0.62


def _fmt(t: float) -> str:
    """Segundos -> h:mm:ss.cc (centisegundos) para ASS."""
    if t < 0:
        t = 0.0
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _clean(text: str) -> str:
    return text.strip().upper().replace("{", "").replace("}", "")


def _group(words: list[Word]) -> list[list[Word]]:
    groups: list[list[Word]] = []
    current: list[Word] = []
    for w in words:
        if not w.text.strip():
            continue
        if current:
            gap = w.start - current[-1].end
            if len(current) >= _MAX_WORDS or gap > _MAX_GAP:
                groups.append(current)
                current = []
        current.append(w)
    if current:
        groups.append(current)
    return groups


def _wrap(tokens: list[str], max_chars: int) -> list[list[int]]:
    """Reparte índices de tokens en líneas que no superen max_chars."""
    lines: list[list[int]] = []
    cur: list[int] = []
    cur_len = 0
    for i, tok in enumerate(tokens):
        extra = len(tok) + (1 if cur else 0)
        if cur and cur_len + extra > max_chars:
            lines.append(cur)
            cur, cur_len = [i], len(tok)
        else:
            cur.append(i)
            cur_len += extra
    if cur:
        lines.append(cur)
    return lines


def _render_group(group: list[Word], max_chars: int) -> str:
    """Texto del grupo en mayúsculas, con la palabra más larga resaltada y
    envuelto en líneas (`\\N`) para que quepa en el ancho del frame."""
    tokens = [_clean(w.text) for w in group]
    if not any(tokens):
        return ""
    emphasis = max(range(len(tokens)), key=lambda i: len(tokens[i]))

    def fmt(i: int) -> str:
        if i == emphasis and len(tokens[i]) >= 4:
            return r"{\c&H00FFFF&}" + tokens[i] + r"{\c&HFFFFFF&}"
        return tokens[i]

    line_groups = _wrap(tokens, max_chars)
    rendered = [" ".join(fmt(i) for i in line) for line in line_groups]
    return r"\N".join(rendered)


def build_ass(words: list[Word], out_path: Path, *, width: int, height: int) -> Path:
    fontsize = max(58, int(height * 0.047))  # ~90px en 1920
    margin_h = max(40, int(width * 0.06))    # margen lateral (padding seguro)
    margin_v = int(height * 0.28)            # sube el texto desde abajo
    outline = max(4, int(fontsize * 0.08))

    usable_w = width - 2 * margin_h
    max_chars = max(8, int(usable_w / (_CHAR_W_RATIO * fontsize)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,{fontsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},3,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = []
    groups = _group(words)
    for gi, group in enumerate(groups):
        text = _render_group(group, max_chars)
        if not text:
            continue
        start = group[0].start
        # El subtítulo dura hasta el inicio del siguiente grupo (sin huecos).
        if gi + 1 < len(groups):
            end = groups[gi + 1][0].start
        else:
            end = group[-1].end + 0.4
        # Aparición rápida tipo "pop".
        text = r"{\fad(80,40)}" + text
        lines.append(
            f"Dialogue: 0,{_fmt(start)},{_fmt(end)},Default,,0,0,0,,{text}"
        )

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path
