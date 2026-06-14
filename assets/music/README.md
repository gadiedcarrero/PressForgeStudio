# Biblioteca de música

Mete aquí pistas de audio **royalty-free** (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`).
El sistema las usa como música de fondo, mezclada por debajo de la narración.

## Cómo se eligen

- **Web UI** → selector "Música de fondo": *(sin música)*, *🎲 Auto*, o una pista concreta.
- **CLI** → `--music auto` · `--music nombre_pista` · `--music ruta\a\audio.mp3`
- **Auto** intenta casar el nombre del archivo con el nicho. Si nombras las pistas
  por tono (`epic.mp3`, `mystery.mp3`, `war_drums.mp3`, `sad_piano.mp3`), el match
  es mejor; si no, elige una al azar.

## De dónde sacar música libre

- Pixabay Music, Free Music Archive, YouTube Audio Library, Incompetech (Kevin MacLeod).
- Revisa siempre la licencia para uso comercial / atribución.

## Más adelante

Música generada por IA (MusicGen vía Replicate, Stable Audio…) se añadirá como otro
`MusicProvider` con la misma interfaz, sin tocar el pipeline.
