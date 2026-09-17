# YT Downloader

Einfaches interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio (MP3).

## Unterstützte Plattformen

| Betriebssystem | x86-64 | ARM64 |
|----------------|--------|-------|
| Linux          | ✅     | ✅ (aarch64, z.B. Raspberry Pi) |
| Windows        | ✅     | ✅ (ffmpeg läuft über die x64-Emulation von Windows 11) |
| macOS          | ✅ (Intel) | ✅ (Apple Silicon) |

## Voraussetzungen

- **Python 3.9 oder neuer** (empfohlen: 3.10+, yt-dlp hat 3.9 als veraltet markiert)
- ffmpeg — wird automatisch über `static-ffmpeg` bereitgestellt, kein manuelles Install nötig

## Installation

```bash
pip install -r requirements.txt
```

## Benutzung

```bash
python yt_downloader.py
```

Das Tool fragt dann Schritt für Schritt:
1. YouTube-URL
2. Format: `video` oder `audio`
3. Auflösung (bei Video): z.B. 1080p, 720p …
4. Speicherort (Standard: `~/Downloads`)
5. Dateiname (Standard: Video-Titel)

## Hinweise

- Videos werden immer als **H.264/AAC MP4 in yuv420p** gespeichert — abspielbar auf
  jedem gängigen Gerät. Das gilt auch für HDR-Quellen: YouTube liefert diese als
  10-Bit VP9/AV1 aus, was sonst zu H.264 „High 10" würde, das kaum ein
  Hardware-Decoder (Smart-TV, Handy, QuickTime) unterstützt.
- Audio wird als MP3 mit 192 kbit/s gespeichert
- Dateinamen werden so bereinigt, dass sie unter Windows, macOS und Linux
  gleichermaßen gültig sind (verbotene Zeichen, reservierte Namen wie `CON`,
  Punkte am Ende, 255-Byte-Grenze der Dateisysteme)
- Falls YouTube den Zugriff blockiert, bietet das Tool einen Cookie-Fallback über
  den Browser an. Safari wird dabei nur unter macOS angeboten.

### ffmpeg manuell installieren

Nur nötig, wenn der automatische Download fehlschlägt (z.B. ohne Internetzugang
oder hinter einer Firewall):

```bash
# Windows
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg      # Debian / Ubuntu / Raspberry Pi OS
sudo dnf install ffmpeg      # Fedora
sudo pacman -S ffmpeg        # Arch
```

### Hinweis zu ARM-Geräten

Auf leistungsschwachen ARM-Boards (Raspberry Pi & Co) kann das H.264-Re-Encoding
bei langen oder hochauflösenden Videos deutlich dauern, da es in Software läuft.
Wähle dort ggf. eine niedrigere Auflösung.
