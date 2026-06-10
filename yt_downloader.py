#!/usr/bin/env python3
"""
YT Downloader — Interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio.

Abhängigkeiten: yt-dlp, rich
Optional:       ffmpeg (für Audio-Extraktion und Format-Konvertierung)
"""

import os
import sys
from pathlib import Path

# Abhängigkeiten prüfen und hilfreiche Fehlermeldung ausgeben
try:
    import yt_dlp
except ImportError:
    print("Fehlende Abhängigkeit: yt-dlp")
    print("Installation: pip install yt-dlp")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.text import Text
    from rich.rule import Rule
except ImportError:
    print("Fehlende Abhängigkeit: rich")
    print("Installation: pip install rich")
    sys.exit(1)


console = Console()


# ─── UI-Hilfsfunktionen ───────────────────────────────────────────────────────

def show_header():
    """Zeigt den App-Header im Terminal an."""
    console.print()
    console.print(Panel.fit(
        "[bold blue]YT Downloader[/bold blue]\n"
        "[dim]YouTube Videos & Audio einfach herunterladen[/dim]",
        border_style="blue",
        padding=(1, 4),
    ))
    console.print()


def show_video_info(info: dict):
    """Zeigt Titel, Kanal und Dauer des gefundenen Videos an."""
    title    = info.get("title", "Unbekannt")
    uploader = info.get("uploader", "Unbekannt")
    duration = info.get("duration") or 0
    minutes, seconds = divmod(int(duration), 60)

    console.print(Panel(
        f"[bold white]{title}[/bold white]\n"
        f"[dim]Kanal: {uploader}  |  Dauer: {minutes}:{seconds:02d}[/dim]",
        title="[green]Video gefunden[/green]",
        border_style="green",
    ))
    console.print()


# ─── Format- und Qualitätsauswahl ────────────────────────────────────────────

def fetch_video_info(url: str) -> dict:
    """Ruft Metadaten und verfügbare Formate von YouTube ab, ohne zu downloaden."""
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        # download=False → nur Metadaten abrufen
        return ydl.extract_info(url, download=False)


def ask_download_type() -> str:
    """Fragt ob Video (mp4) oder nur Audio (mp3) gewünscht ist."""
    return Prompt.ask(
        "[cyan]Format wählen[/cyan]",
        choices=["video", "audio"],
        default="video",
    )


def ask_video_quality(info: dict) -> str:
    """
    Listet verfügbare Videoauflösungen auf und lässt den User eine wählen.
    Gibt einen yt-dlp Format-Selector-String zurück.
    """
    formats = info.get("formats", [])

    # Alle eindeutigen Auflösungen sammeln (nur echte Video-Streams)
    heights = sorted(
        {f["height"] for f in formats if f.get("vcodec") != "none" and f.get("height")},
        reverse=True,
    )

    if not heights:
        # Kein Format mit Auflösungsinfo gefunden — bestes verfügbares nehmen
        return "bestvideo+bestaudio/best"

    # Qualitätstabelle anzeigen
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Nr.", style="cyan", width=4)
    table.add_column("Auflösung", style="green")

    for i, h in enumerate(heights, start=1):
        table.add_row(str(i), f"{h}p")

    console.print("[bold]Verfügbare Auflösungen:[/bold]")
    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[cyan]Auflösung wählen[/cyan]",
        choices=[str(i) for i in range(1, len(heights) + 1)],
        default="1",
    )

    selected = heights[int(choice) - 1]
    # Bestes Video bis zur gewählten Auflösung + bestes Audio kombinieren
    return f"bestvideo[height<={selected}]+bestaudio/best[height<={selected}]"


# ─── Pfad- und Dateinamen-Eingabe ─────────────────────────────────────────────

def ask_output_path() -> Path:
    """Fragt nach dem Zielordner und erstellt ihn bei Bedarf."""
    # Standardpfad: ~/Downloads (auf allen Betriebssystemen verfügbar)
    default = str(Path.home() / "Downloads")

    raw = Prompt.ask("[cyan]Speicherort[/cyan]", default=default)
    path = Path(raw).expanduser().resolve()

    if not path.exists():
        if Confirm.ask(f"[yellow]Ordner '{path}' existiert nicht. Erstellen?[/yellow]"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            console.print("[red]Abgebrochen.[/red]")
            sys.exit(0)

    return path


def ask_filename(default_title: str) -> str:
    """Fragt nach dem Dateinamen (ohne Endung) und bereinigt unerlaubte Zeichen."""
    # Zeichen entfernen, die auf Windows/macOS/Linux Probleme machen
    safe_default = "".join(
        c for c in default_title if c.isalnum() or c in (" ", "-", "_", ".")
    ).strip()

    return Prompt.ask("[cyan]Dateiname (ohne Endung)[/cyan]", default=safe_default)


# ─── Download ─────────────────────────────────────────────────────────────────

def build_ydl_opts(format_selector: str, output_template: str, is_audio: bool) -> dict:
    """Erstellt die yt-dlp Optionen abhängig vom gewählten Format."""
    opts = {
        "format":      format_selector,
        "outtmpl":     output_template,
        # Fortschrittsanzeige von yt-dlp selbst nutzen
        "quiet":       False,
        "no_warnings": True,
        # Zusammenführen von Video+Audio-Streams mit ffmpeg falls vorhanden
        "merge_output_format": "mp4" if not is_audio else None,
    }

    if is_audio:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",  # 192 kbps — guter Kompromiss aus Qualität & Größe
        }]

    return opts


def download(url: str, format_selector: str, output_path: Path, filename: str, is_audio: bool):
    """Führt den eigentlichen Download durch."""
    # %(ext)s wird von yt-dlp automatisch durch die korrekte Endung ersetzt
    template = str(output_path / filename) + ".%(ext)s"
    opts = build_ydl_opts(format_selector, template, is_audio)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


# ─── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    show_header()

    # Schritt 1: YouTube-URL eingeben
    url = Prompt.ask("[cyan]YouTube-URL[/cyan]")
    console.print()

    # Schritt 2: Video-Metadaten abrufen
    console.print("[dim]Lade Video-Informationen …[/dim]")
    try:
        info = fetch_video_info(url)
    except yt_dlp.utils.DownloadError as e:
        console.print(f"\n[red]Fehler: {e}[/red]")
        sys.exit(1)

    show_video_info(info)

    # Schritt 3: Video oder Audio?
    download_type = ask_download_type()
    is_audio = download_type == "audio"
    console.print()

    # Schritt 4: Qualität / Auflösung wählen
    if is_audio:
        format_selector = "bestaudio/best"
    else:
        format_selector = ask_video_quality(info)
    console.print()

    # Schritt 5: Zielordner
    output_path = ask_output_path()
    console.print()

    # Schritt 6: Dateiname
    video_title = info.get("title", "download")
    filename = ask_filename(video_title)
    console.print()

    # Schritt 7: Download starten
    console.print(Rule("[bold green]Download[/bold green]"))
    console.print()

    try:
        download(url, format_selector, output_path, filename, is_audio)
    except yt_dlp.utils.DownloadError as e:
        console.print(f"\n[red]Download fehlgeschlagen: {e}[/red]")
        console.print("[dim]Tipp: Stelle sicher, dass ffmpeg installiert ist (für HD-Videos und Audio).[/dim]")
        sys.exit(1)

    # Erfolgsmeldung
    ext = "mp3" if is_audio else "mp4"
    final_file = output_path / f"{filename}.{ext}"

    console.print()
    console.print(Panel(
        f"[green]Erfolgreich gespeichert![/green]\n[dim]{final_file}[/dim]",
        border_style="green",
    ))
    console.print()


if __name__ == "__main__":
    main()
