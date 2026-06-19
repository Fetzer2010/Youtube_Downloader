# YT Downloader

Einfaches interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio (MP3).
Läuft auf Windows, macOS und Linux.

## Voraussetzungen

- Python 3.10+
- ffmpeg — wird automatisch über `static-ffmpeg` mitgeliefert, kein manuelles Install nötig

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

- Videos werden immer als H.264/AAC MP4 gespeichert — kompatibel mit allen gängigen Geräten und Playern
- Audio wird als MP3 mit 192 kbit/s gespeichert
- Falls YouTube den Zugriff blockiert, bietet das Tool einen Cookie-Fallback über den Browser an
