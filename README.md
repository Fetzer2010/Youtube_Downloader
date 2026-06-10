# YT Downloader

Einfaches interaktives CLI-Tool zum Herunterladen von YouTube Videos und Audio (MP3).
Läuft auf Windows, macOS und Linux.

## Voraussetzungen

- Python 3.8+
- [ffmpeg](https://ffmpeg.org/download.html) — für HD-Downloads und MP3-Extraktion

## Installation

```bash
# 1. Abhängigkeiten installieren
pip install -r requirements.txt

# 2. (Optional) ffmpeg installieren
#    Windows:  winget install ffmpeg
#    macOS:    brew install ffmpeg
#    Linux:    sudo apt install ffmpeg
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

- Ohne ffmpeg sind nur Qualitäten bis 720p ohne separaten Download verfügbar
- MP3-Extraktion erfordert zwingend ffmpeg
