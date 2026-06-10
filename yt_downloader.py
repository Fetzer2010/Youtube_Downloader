#!/usr/bin/env python3
"""
YT Downloader — Interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio.

Abhängigkeiten: yt-dlp, rich
Optional:       ffmpeg (für Audio-Extraktion und Format-Konvertierung)
"""

import os
import sys
from pathlib import Path

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
    from rich.rule import Rule
except ImportError:
    print("Fehlende Abhängigkeit: rich")
    print("Installation: pip install rich")
    sys.exit(1)


console = Console()

# Browser die yt-dlp unterstützt — Reihenfolge = Anzeige-Reihenfolge im Menü
SUPPORTED_BROWSERS = ["chrome", "edge", "firefox", "chromium", "brave", "opera", "vivaldi", "safari"]

# Schlüsselwort das im Fehlertext erscheint wenn YouTube Bot-Schutz greift
BOT_ERROR_KEYWORD = "Sign in to confirm you're not a bot"


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


# ─── Browser-Cookie-Auswahl ───────────────────────────────────────────────────

def ask_browser() -> str:
    """
    Zeigt eine Auswahl der unterstützten Browser und gibt den gewählten Namen zurück.
    yt-dlp liest dann die Cookies direkt aus dem lokalen Browser-Profil.
    """
    console.print()
    console.print(Panel(
        "[yellow]YouTube hat den Zugriff blockiert (Bot-Schutz).[/yellow]\n"
        "Lösung: Cookies aus einem eingeloggten Browser weitergeben.\n"
        "[dim]Der Browser muss auf diesem Gerät installiert und bei YouTube eingeloggt sein.[/dim]",
        title="[yellow]Authentifizierung erforderlich[/yellow]",
        border_style="yellow",
    ))
    console.print()

    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("Nr.", style="cyan", width=4)
    table.add_column("Browser", style="green")

    for i, browser in enumerate(SUPPORTED_BROWSERS, start=1):
        table.add_row(str(i), browser.capitalize())

    console.print("[bold]Welchen Browser möchtest du verwenden?[/bold]")
    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[cyan]Browser wählen[/cyan]",
        choices=[str(i) for i in range(1, len(SUPPORTED_BROWSERS) + 1)],
        default="1",
    )

    return SUPPORTED_BROWSERS[int(choice) - 1]


# ─── Format- und Qualitätsauswahl ────────────────────────────────────────────

def build_base_opts(browser: str | None = None) -> dict:
    """Erstellt die gemeinsamen yt-dlp Basis-Optionen, optional mit Browser-Cookies."""
    opts: dict = {"quiet": True, "no_warnings": True}
    if browser:
        # Tuple-Format: (browser, profile, keyring, container) — nur Name nötig
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def fetch_video_info(url: str, browser: str | None = None) -> dict:
    """
    Ruft Metadaten und verfügbare Formate von YouTube ab, ohne zu downloaden.
    Bei gesetztem `browser` werden dessen Cookies zur Authentifizierung genutzt.
    """
    opts = build_base_opts(browser)
    with yt_dlp.YoutubeDL(opts) as ydl:
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

    heights = sorted(
        {f["height"] for f in formats if f.get("vcodec") != "none" and f.get("height")},
        reverse=True,
    )

    if not heights:
        return "bestvideo+bestaudio/best"

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
    return f"bestvideo[height<={selected}]+bestaudio/best[height<={selected}]"


# ─── Pfad- und Dateinamen-Eingabe ─────────────────────────────────────────────

def ask_output_path() -> Path:
    """Fragt nach dem Zielordner und erstellt ihn bei Bedarf."""
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
    safe_default = "".join(
        c for c in default_title if c.isalnum() or c in (" ", "-", "_", ".")
    ).strip()
    return Prompt.ask("[cyan]Dateiname (ohne Endung)[/cyan]", default=safe_default)


# ─── Download ─────────────────────────────────────────────────────────────────

def build_ydl_opts(
    format_selector: str,
    output_template: str,
    is_audio: bool,
    browser: str | None = None,
) -> dict:
    """Erstellt die vollständigen yt-dlp Optionen für den Download."""
    opts = build_base_opts(browser)
    opts.update({
        "format":              format_selector,
        "outtmpl":             output_template,
        "quiet":               False,
        "no_warnings":         True,
        "merge_output_format": "mp4" if not is_audio else None,
    })

    if is_audio:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]

    return opts


def download(
    url: str,
    format_selector: str,
    output_path: Path,
    filename: str,
    is_audio: bool,
    browser: str | None = None,
):
    """Führt den eigentlichen Download durch."""
    template = str(output_path / filename) + ".%(ext)s"
    opts = build_ydl_opts(format_selector, template, is_audio, browser)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


# ─── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    show_header()

    # Schritt 1: URL
    url = Prompt.ask("[cyan]YouTube-URL[/cyan]")
    console.print()

    # Schritt 2: Video-Metadaten abrufen — bei Bot-Fehler automatisch Browser fragen
    browser: str | None = None
    console.print("[dim]Lade Video-Informationen …[/dim]")
    try:
        info = fetch_video_info(url)
    except yt_dlp.utils.DownloadError as e:
        if BOT_ERROR_KEYWORD not in str(e):
            console.print(f"\n[red]Fehler: {e}[/red]")
            sys.exit(1)

        # Bot-Schutz erkannt → Browser-Cookies anfordern und nochmal versuchen
        browser = ask_browser()
        console.print(f"\n[dim]Lade Video-Informationen mit {browser.capitalize()}-Cookies …[/dim]")
        try:
            info = fetch_video_info(url, browser)
        except yt_dlp.utils.DownloadError as e2:
            console.print(f"\n[red]Fehler: {e2}[/red]")
            console.print(
                "[dim]Stelle sicher, dass du in diesem Browser bei YouTube eingeloggt bist.[/dim]"
            )
            sys.exit(1)

    show_video_info(info)

    # Schritt 3: Video oder Audio?
    download_type = ask_download_type()
    is_audio = download_type == "audio"
    console.print()

    # Schritt 4: Qualität wählen
    if is_audio:
        format_selector = "bestaudio/best"
    else:
        format_selector = ask_video_quality(info)
    console.print()

    # Schritt 5: Zielordner
    output_path = ask_output_path()
    console.print()

    # Schritt 6: Dateiname
    filename = ask_filename(info.get("title", "download"))
    console.print()

    # Schritt 7: Download
    console.print(Rule("[bold green]Download[/bold green]"))
    console.print()

    try:
        download(url, format_selector, output_path, filename, is_audio, browser)
    except yt_dlp.utils.DownloadError as e:
        console.print(f"\n[red]Download fehlgeschlagen: {e}[/red]")
        console.print("[dim]Tipp: Stelle sicher, dass ffmpeg installiert ist (für HD-Videos und Audio).[/dim]")
        sys.exit(1)

    ext = "mp3" if is_audio else "mp4"
    console.print()
    console.print(Panel(
        f"[green]Erfolgreich gespeichert![/green]\n[dim]{output_path / filename}.{ext}[/dim]",
        border_style="green",
    ))
    console.print()


if __name__ == "__main__":
    main()
