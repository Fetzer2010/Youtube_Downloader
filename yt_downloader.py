#!/usr/bin/env python3
"""
YT Downloader — Interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio.

Unterstützte Plattformen:
    Windows  x86-64 / ARM64
    macOS    Intel  / Apple Silicon
    Linux    x86-64 / ARM64 (aarch64)

Benötigt Python 3.9 oder neuer.

Abhängigkeiten: yt-dlp, rich
Optional:       ffmpeg (wird via static-ffmpeg automatisch bereitgestellt)
"""

# Muss die erste Anweisung nach dem Docstring sein. Sorgt dafür, dass
# `str | None`-Annotationen (PEP 604) auch unter Python 3.9 funktionieren —
# dort werden Annotationen sonst zur Laufzeit ausgewertet und werfen TypeError.
from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import sys
from pathlib import Path

MIN_PYTHON = (3, 9)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        "YT Downloader benötigt Python {}.{} oder neuer — gefunden: {}.{}\n".format(
            MIN_PYTHON[0], MIN_PYTHON[1], sys.version_info[0], sys.version_info[1]
        )
    )
    sys.exit(1)


def _setup_console_encoding() -> None:
    """
    Windows-Terminals laufen je nach Version noch mit einer Legacy-Codepage
    (z.B. cp1252). Rich gibt Box-Zeichen und Umlaute aus, was dort sonst mit
    UnicodeEncodeError abbricht. Unter macOS/Linux ist UTF-8 bereits Standard.
    """
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_setup_console_encoding()


try:
    import yt_dlp
except ImportError:
    sys.stderr.write(
        "Fehlende Abhängigkeit: yt-dlp\n"
        "Installation: {} -m pip install -r requirements.txt\n".format(sys.executable)
    )
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt, Confirm
    from rich.table import Table
    from rich.rule import Rule
except ImportError:
    sys.stderr.write(
        "Fehlende Abhängigkeit: rich\n"
        "Installation: {} -m pip install -r requirements.txt\n".format(sys.executable)
    )
    sys.exit(1)


console = Console()


# ─── Plattform-Erkennung ──────────────────────────────────────────────────────

def platform_label() -> str:
    """Lesbare Beschreibung von OS und Architektur, z.B. 'Linux aarch64'."""
    return "{} {}".format(platform.system(), platform.machine() or "unbekannt")


def supported_browsers() -> list[str]:
    """
    Browser, aus denen yt-dlp auf diesem Betriebssystem Cookies lesen kann.
    Safari existiert ausschließlich unter macOS — es auf Windows/Linux
    anzubieten führt nur zu verwirrenden Fehlermeldungen.
    """
    browsers = ["chrome", "edge", "firefox", "chromium", "brave", "opera", "vivaldi"]
    if sys.platform == "darwin":
        browsers.append("safari")
    return browsers


def ffmpeg_install_hint() -> str:
    """Passender manueller Installationsbefehl für das aktuelle System."""
    if sys.platform == "win32":
        return "winget install Gyan.FFmpeg     (alternativ: choco install ffmpeg)"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return (
        "sudo apt install ffmpeg      (Debian / Ubuntu / Raspberry Pi OS)\n"
        "sudo dnf install ffmpeg      (Fedora)\n"
        "sudo pacman -S ffmpeg        (Arch)"
    )


def ensure_ffmpeg() -> tuple[bool, str]:
    """
    Stellt sicher, dass ffmpeg und ffprobe aufrufbar sind.

    Reihenfolge:
      1. Systemweite Installation (funktioniert auf jeder Architektur)
      2. static-ffmpeg — lädt beim ersten Aufruf passende Binaries für
         win32 / darwin / darwin_arm64 / linux / linux_arm64 herunter

    Gibt (erfolgreich, Quelle-oder-Fehlermeldung) zurück. Ein Fehlschlag ist
    nicht fatal: Downloads einzelner, bereits fertig gemuxter Formate laufen
    auch ohne ffmpeg.
    """
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True, "systemweit installiert"

    try:
        import static_ffmpeg
    except ImportError:
        return False, "static-ffmpeg ist nicht installiert"

    console.print(
        "[dim]ffmpeg nicht gefunden — lade Binaries für {} herunter "
        "(einmalig, ca. 100 MB) …[/dim]".format(platform_label())
    )
    try:
        static_ffmpeg.add_paths(weak=True)
    except Exception as exc:
        # Kein Netz, Firewall, oder keine Binaries für diese Architektur
        # (z.B. Windows ARM64 ohne x64-Emulation).
        return False, "{}: {}".format(type(exc).__name__, exc)

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True, "von static-ffmpeg bereitgestellt"
    return False, "static-ffmpeg lieferte keine lauffähigen Binaries"


# ─── Dateinamen und Pfade (plattformübergreifend) ─────────────────────────────

# Unter Windows verbotene Gerätenamen — eine Datei "CON.mp4" lässt sich dort
# nicht anlegen, egal welche Endung sie hat.
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_WINDOWS_RESERVED |= {"COM{}".format(i) for i in range(1, 10)}
_WINDOWS_RESERVED |= {"LPT{}".format(i) for i in range(1, 10)}

# Zeichen, die unter Windows verboten und unter macOS/Linux zumindest heikel
# sind (":" erzeugt im Finder Chaos, "/" ist überall ein Trenner).
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _truncate_bytes(name: str, max_bytes: int = 150) -> str:
    """
    Kürzt auf `max_bytes` UTF-8-Bytes. Die meisten Dateisysteme (ext4, APFS,
    NTFS) begrenzen einen Pfadbestandteil auf 255 Bytes — bei japanischen oder
    Emoji-Titeln sind das deutlich weniger Zeichen als Bytes.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """
    Macht aus einem beliebigen Video-Titel oder einer Nutzereingabe einen
    Dateinamen, der unter Windows, macOS und Linux gleichermaßen gültig ist.
    """
    cleaned = _ILLEGAL_CHARS.sub("_", name)
    # "%" kollidiert mit den Output-Templates von yt-dlp (z.B. "%(ext)s").
    cleaned = cleaned.replace("%", "_")
    # Windows schneidet Punkte und Leerzeichen am Ende stillschweigend ab —
    # der angezeigte Pfad würde dann nicht zur echten Datei passen.
    cleaned = cleaned.strip().rstrip(". ")
    cleaned = _truncate_bytes(cleaned).rstrip(". ")

    if not cleaned:
        return fallback
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    return cleaned


def normalize_path_input(raw: str) -> str:
    """
    Räumt einen per Hand eingegebenen oder hineingezogenen Pfad auf.

    Windows' "Als Pfad kopieren" liefert den Pfad in Anführungszeichen; das
    Terminal von macOS/Linux escapt beim Drag & Drop Leerzeichen mit Backslash
    (unter Windows wäre der Backslash dagegen der Trennzeichen selbst).
    """
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    if sys.platform != "win32":
        text = text.replace("\\ ", " ")
    # Löst %USERPROFILE% (Windows) bzw. $HOME (POSIX) auf.
    return os.path.expandvars(text).strip()


# ─── UI-Hilfsfunktionen ───────────────────────────────────────────────────────

def show_header():
    """Zeigt den App-Header im Terminal an."""
    console.print()
    console.print(Panel.fit(
        "[bold blue]YT Downloader[/bold blue]\n"
        "[dim]YouTube Videos & Audio einfach herunterladen[/dim]\n"
        "[dim]{}[/dim]".format(platform_label()),
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
        "[bold white]{}[/bold white]\n"
        "[dim]Kanal: {}  |  Dauer: {}:{:02d}[/dim]".format(title, uploader, minutes, seconds),
        title="[green]Video gefunden[/green]",
        border_style="green",
    ))
    console.print()


# ─── Browser-Cookie-Auswahl ───────────────────────────────────────────────────

def ask_browser() -> str:
    """
    Zeigt eine Auswahl der auf diesem System unterstützten Browser und gibt den
    gewählten Namen zurück. yt-dlp liest die Cookies dann direkt aus dem
    lokalen Browser-Profil.
    """
    browsers = supported_browsers()

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

    for i, browser in enumerate(browsers, start=1):
        table.add_row(str(i), browser.capitalize())

    console.print("[bold]Welchen Browser möchtest du verwenden?[/bold]")
    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[cyan]Browser wählen[/cyan]",
        choices=[str(i) for i in range(1, len(browsers) + 1)],
        default="1",
    )

    return browsers[int(choice) - 1]


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
        info = ydl.extract_info(url, download=False)

    if not info:
        raise yt_dlp.utils.DownloadError("Keine Video-Informationen erhalten.")
    # Bei Playlists und Kanälen liefert yt-dlp eine Sammlung — wir nehmen den
    # ersten Eintrag, damit Formatauswahl und Titel funktionieren.
    if info.get("_type") in ("playlist", "multi_video") and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise yt_dlp.utils.DownloadError("Die Playlist enthält keine abspielbaren Videos.")
        info = entries[0]
    return info


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
        table.add_row(str(i), "{}p".format(h))

    console.print("[bold]Verfügbare Auflösungen:[/bold]")
    console.print(table)
    console.print()

    choice = Prompt.ask(
        "[cyan]Auflösung wählen[/cyan]",
        choices=[str(i) for i in range(1, len(heights) + 1)],
        default="1",
    )

    selected = heights[int(choice) - 1]
    return "bestvideo[height<={h}]+bestaudio/best[height<={h}]".format(h=selected)


# ─── Pfad- und Dateinamen-Eingabe ─────────────────────────────────────────────

def ask_output_path() -> Path:
    """Fragt nach dem Zielordner und erstellt ihn bei Bedarf."""
    default = str(Path.home() / "Downloads")
    raw = Prompt.ask("[cyan]Speicherort[/cyan]", default=default)
    text = normalize_path_input(raw) or default

    try:
        path = Path(text).expanduser().resolve()
    except (OSError, ValueError) as exc:
        console.print("[red]Ungültiger Pfad: {}[/red]".format(exc))
        sys.exit(1)

    if not path.exists():
        if Confirm.ask("[yellow]Ordner '{}' existiert nicht. Erstellen?[/yellow]".format(path)):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                console.print("[red]Ordner konnte nicht erstellt werden: {}[/red]".format(exc))
                sys.exit(1)
        else:
            console.print("[red]Abgebrochen.[/red]")
            sys.exit(0)

    return path


def ask_filename(default_title: str) -> str:
    """Fragt nach dem Dateinamen (ohne Endung) und macht ihn systemtauglich."""
    answer = Prompt.ask(
        "[cyan]Dateiname (ohne Endung)[/cyan]",
        default=sanitize_filename(default_title),
    )
    # Auch die freie Eingabe wird bereinigt — ein getipptes "a/b" oder "CON"
    # würde sonst je nach Betriebssystem still fehlschlagen.
    return sanitize_filename(answer)


# ─── Download ─────────────────────────────────────────────────────────────────

# Re-encode to H.264/AAC so every device can play the file.
# Preferred avc1 format selector already avoids re-encoding in most cases,
# but this guarantees compatibility when only VP9 or AV1 streams are available.
#
# -pix_fmt yuv420p ist dabei entscheidend: YouTube liefert HDR-Videos als
# 10-Bit VP9 (Profile 2) bzw. AV1 aus. Ohne diese Zeile erzeugt libx264 daraus
# H.264 "High 10", das kaum ein Hardware-Decoder (Smart-TV, Handy, QuickTime)
# abspielen kann — genau das, was hier vermieden werden soll.
H264_FFMPEG_ARGS = (
    "-c:v", "libx264", "-crf", "20", "-preset", "fast",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
)


def build_ydl_opts(
    format_selector: str,
    output_template: str,
    is_audio: bool,
    browser: str | None = None,
) -> dict:
    """Erstellt die vollständigen yt-dlp Optionen für den Download."""
    opts = build_base_opts(browser)
    opts.update({
        "format":      format_selector,
        "outtmpl":     output_template,
        "quiet":       False,
        "no_warnings": True,
    })

    if is_audio:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
    else:
        opts["merge_output_format"] = "mp4"
        # Der Merger läuft nur, wenn Video- und Audiospur getrennt geladen und
        # zusammengefügt werden. Wählt yt-dlp dagegen ein bereits fertig
        # gemuxtes Format (z.B. eine einzelne .webm), bliebe die Datei sonst
        # unkonvertiert — der VideoConvertor deckt genau diesen Fall ab. Bei
        # einer Datei, die schon mp4 ist, überspringt er sich selbst.
        opts["postprocessors"] = [{
            "key":            "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }]
        opts["postprocessor_args"] = {
            "merger":         list(H264_FFMPEG_ARGS),
            "videoconvertor": list(H264_FFMPEG_ARGS),
        }

    return opts


def _resolve_output_file(info, output_path: Path, filename: str) -> Path | None:
    """
    Ermittelt, wie die fertige Datei nach allen Postprozessoren wirklich heißt.

    Die Endung vorherzusagen geht schief: je nach gewähltem Format greift mal
    der Merger, mal der Konverter, mal keiner von beiden. yt-dlp trägt den
    endgültigen Pfad in `requested_downloads` ein.
    """
    if isinstance(info, dict):
        for entry in info.get("requested_downloads") or []:
            candidate = entry.get("filepath")
            if candidate and Path(candidate).exists():
                return Path(candidate)

    # Fallback: im Zielordner nach "<name>.*" suchen. glob.escape schützt vor
    # Sonderzeichen wie "[" im Dateinamen.
    matches = [Path(m) for m in glob.glob(glob.escape(str(output_path / filename)) + ".*")]
    if not matches:
        return None
    # Zwischendateien (.part, .ytdl, .f137) ignorieren, größte echte Datei nehmen
    finals = [m for m in matches if m.suffix not in (".part", ".ytdl", ".temp")]
    return max(finals or matches, key=lambda m: m.stat().st_size)


def download(
    url: str,
    format_selector: str,
    output_path: Path,
    filename: str,
    is_audio: bool,
    browser: str | None = None,
) -> Path | None:
    """Führt den eigentlichen Download durch und gibt die erzeugte Datei zurück."""
    # os.fspath statt String-Verkettung: liefert auf jedem OS den korrekten
    # Trenner ("\" unter Windows, "/" sonst).
    template = os.fspath(output_path / filename) + ".%(ext)s"
    opts = build_ydl_opts(format_selector, template, is_audio, browser)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    return _resolve_output_file(info, output_path, filename)


# ─── Hauptprogramm ────────────────────────────────────────────────────────────

def main():
    show_header()

    # Schritt 0: ffmpeg bereitstellen (nötig für HD-Merge und MP3-Extraktion)
    ffmpeg_ok, ffmpeg_source = ensure_ffmpeg()
    if ffmpeg_ok:
        console.print("[dim]ffmpeg: {}[/dim]".format(ffmpeg_source))
    else:
        console.print(Panel(
            "[yellow]ffmpeg ist nicht verfügbar.[/yellow]\n"
            "[dim]Grund: {}[/dim]\n\n"
            "HD-Videos (getrennte Video-/Audiospuren) und MP3-Downloads\n"
            "funktionieren ohne ffmpeg nicht. Manuelle Installation:\n\n"
            "[cyan]{}[/cyan]".format(ffmpeg_source, ffmpeg_install_hint()),
            title="[yellow]Hinweis[/yellow]",
            border_style="yellow",
        ))
    console.print()

    # Schritt 1: URL
    url = Prompt.ask("[cyan]YouTube-URL[/cyan]").strip()
    if not url:
        console.print("[red]Keine URL angegeben.[/red]")
        sys.exit(1)
    console.print()

    # Schritt 2: Video-Metadaten abrufen — bei Fehler Browser-Cookie-Fallback anbieten
    browser: str | None = None
    console.print("[dim]Lade Video-Informationen …[/dim]")
    try:
        info = fetch_video_info(url)
    except yt_dlp.utils.DownloadError:
        # Erster Versuch fehlgeschlagen (häufigste Ursache: YouTube Bot-Schutz)
        # → Browser-Cookies als Fallback anbieten
        browser = ask_browser()
        console.print("\n[dim]Lade Video-Informationen mit {}-Cookies …[/dim]".format(browser.capitalize()))
        try:
            info = fetch_video_info(url, browser)
        except yt_dlp.utils.DownloadError as e2:
            console.print("\n[red]Fehler: {}[/red]".format(e2))
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
    filename = ask_filename(info.get("title") or "download")
    console.print()

    # Schritt 7: Download
    console.print(Rule("[bold green]Download[/bold green]"))
    console.print()

    try:
        result = download(url, format_selector, output_path, filename, is_audio, browser)
    except yt_dlp.utils.DownloadError as e:
        console.print("\n[red]Download fehlgeschlagen: {}[/red]".format(e))
        if not ffmpeg_ok:
            console.print("[dim]Wahrscheinliche Ursache: ffmpeg fehlt. Installation:[/dim]")
            console.print("[cyan]{}[/cyan]".format(ffmpeg_install_hint()))
        sys.exit(1)

    if result is None:
        # Der Download meldete Erfolg, aber es liegt keine Datei im Zielordner.
        console.print()
        console.print(Panel(
            "[yellow]Der Download lief durch, es wurde aber keine Datei gefunden.[/yellow]\n"
            "[dim]Erwartet in: {}[/dim]".format(output_path),
            border_style="yellow",
        ))
        sys.exit(1)

    size_mb = result.stat().st_size / (1024 * 1024)
    console.print()
    console.print(Panel(
        "[green]Erfolgreich gespeichert![/green]\n"
        "[dim]{}[/dim]\n"
        "[dim]{:.1f} MB[/dim]".format(result, size_mb),
        border_style="green",
    ))
    console.print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl-C soll keinen Traceback hinterlassen (und unter Windows keinen
        # halb gezeichneten Rich-Rahmen).
        console.print("\n[dim]Abgebrochen.[/dim]")
        sys.exit(130)
    except EOFError:
        # Ctrl-D bzw. erschöpfte Eingabe bei gepipetem stdin.
        console.print("\n[dim]Eingabe beendet — abgebrochen.[/dim]")
        sys.exit(130)
