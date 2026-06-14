"""CLI de PressForge Studio."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .config import get_settings
from .ffmpeg_utils import has_binary

app = typer.Typer(add_completion=False, help="Fábrica de reels históricos con IA.")
console = Console()


@app.command()
def make(
    niche: str = typer.Argument(..., help="Nicho o tema. Ej: 'muertes absurdas de reyes'"),
    scenes: int = typer.Option(6, "--scenes", "-s", min=3, max=12, help="Número de escenas."),
    voice: Optional[str] = typer.Option(None, "--voice", "-v", help="Voz OpenAI (onyx, nova, echo…)."),
    music: Optional[str] = typer.Option(
        None, "--music", "-m",
        help="Música: 'auto', nombre de pista de assets/music, o ruta a un audio.",
    ),
    extra: Optional[str] = typer.Option(None, "--extra", "-e", help="Indicaciones extra para el guion."),
):
    """Genera un reel end-to-end a partir de un nicho."""
    # Import diferido: así `doctor` funciona aunque falte alguna dependencia pesada.
    from .pipeline import generate_reel

    try:
        result = generate_reel(
            niche, scenes=scenes, extra=extra, music=music, voice=voice, console=console
        )
    except Exception as exc:  # noqa: BLE001 — queremos un mensaje limpio en CLI
        console.print(f"\n[bold red]Error:[/] {exc}")
        raise typer.Exit(1)

    console.print()
    console.print(f"[bold green]🎬 {result.video_path}[/]")
    console.print(f"[dim]Carpeta de trabajo:[/] {result.workdir}")
    console.print(f"[dim]Duración:[/] {result.duration:.1f}s")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host."),
    port: int = typer.Option(8000, help="Puerto."),
):
    """Levanta la Web UI local (formulario + progreso + galería de reels)."""
    import uvicorn

    from .web.app import app as web_app

    console.print(f"[bold green]PressForge Studio[/] → [cyan]http://{host}:{port}[/]")
    console.print("[dim]Ctrl+C para detener.[/]")
    uvicorn.run(web_app, host=host, port=port, log_level="warning")


@app.command()
def music():
    """Lista las pistas de música disponibles en assets/music/."""
    from .registry import get_music_provider

    tracks = get_music_provider().list_tracks()
    if not tracks:
        console.print("[yellow]No hay pistas.[/] Añade audios royalty-free a [cyan]assets/music/[/].")
        return
    console.print(f"[bold]{len(tracks)} pista(s):[/]")
    for t in tracks:
        console.print(f"  ♪ {t}")


@app.command()
def doctor():
    """Verifica que el entorno está listo (ffmpeg, ffprobe, API key)."""
    ok = True

    def check(label: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        mark = "[green]✓[/]" if passed else "[red]✗[/]"
        console.print(f"  {mark} {label}" + (f"  [dim]{hint}[/]" if not passed and hint else ""))
        ok = ok and passed

    console.print("[bold]PressForge · doctor[/]")
    check("ffmpeg", has_binary("ffmpeg"), "instala: winget install --id Gyan.FFmpeg -e")
    check("ffprobe", has_binary("ffprobe"), "viene con ffmpeg")
    check("OPENAI_API_KEY", bool(get_settings().openai_api_key), "ponla en .env")

    console.print()
    if ok:
        console.print("[bold green]Todo listo.[/] Prueba: python -m pressforge make \"curiosidades históricas\"")
    else:
        console.print("[bold red]Faltan requisitos.[/] Revisa lo marcado arriba.")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
