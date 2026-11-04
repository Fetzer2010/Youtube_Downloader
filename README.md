# YT Downloader

A simple, interactive terminal tool for downloading YouTube videos (MP4) and audio (MP3).
Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [rich](https://github.com/Textualize/rich).

## Features

- Guided, step-by-step prompts — no command-line flags to remember
- Choose any available resolution, or download audio only
- Live progress bars with speed and ETA
- Videos are always saved as **H.264/AAC MP4 (yuv420p)** for playback on practically any device
- Audio is saved as **MP3 at 192 kbit/s**
- ffmpeg is provided automatically — no manual install needed
- Safe file names on Windows, macOS and Linux
- Browser-cookie fallback when YouTube's bot protection blocks a request

## Supported platforms

| Operating system | x86-64 | ARM64 |
|------------------|--------|-------|
| Linux            | ✅     | ✅ (aarch64, e.g. Raspberry Pi) |
| Windows          | ✅     | ✅ (Windows 11 only — ffmpeg runs through x64 emulation) |
| macOS            | ✅ (Intel) | ✅ (Apple Silicon) |

32-bit systems (e.g. Raspberry Pi OS 32-bit) are not supported by the automatic ffmpeg download;
install ffmpeg manually there (see below).

## Requirements

- **Python 3.11 or newer** (required by current yt-dlp releases)
- ffmpeg — provided automatically through `static-ffmpeg`; see [Installing ffmpeg manually](#installing-ffmpeg-manually) if that fails

## Installation

```bash
git clone https://github.com/Fetzer2010/Youtube_Downloader.git
cd Youtube_Downloader

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

```bash
python yt_downloader.py
```

The tool then asks, step by step:

1. YouTube URL
2. Format: `video` or `audio`
3. Resolution (video only), e.g. 1080p, 720p …
4. Destination folder (default: `~/Downloads`)
5. File name (default: the video title)

YouTube regularly changes its internals. If downloads suddenly fail, update yt-dlp first:

```bash
pip install -U yt-dlp
```

## Notes

- Videos are always re-encoded to **H.264/AAC MP4 in yuv420p**. This includes HDR sources:
  YouTube serves them as 10-bit VP9/AV1, which would otherwise become H.264 "High 10" —
  something hardly any hardware decoder (smart TV, phone, QuickTime) supports.
- File names are sanitized so they are valid on Windows, macOS and Linux alike
  (forbidden characters, reserved names such as `CON`, trailing dots, the 255-byte
  file-system limit).
- If YouTube blocks access, the tool offers a cookie fallback using your browser.
  Safari is only offered on macOS.
- For playlist URLs, only the first video is downloaded.

### Installing ffmpeg manually

Only needed if the automatic download fails (e.g. no internet access or behind a firewall):

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

### Note for ARM devices

On low-powered ARM boards (Raspberry Pi & co), H.264 re-encoding of long or
high-resolution videos can take a long time because it runs in software.
Consider choosing a lower resolution there.

## Support & feedback

Found a bug, have a question or a feature idea? Open an
[issue](../../issues) or write to [sebastian@finklham.at](mailto:sebastian@finklham.at).

## Donate

If this tool saves you time, you can support its development with a small donation:
[paypal.me/Stodla2010](https://www.paypal.com/paypalme/Stodla2010). Thank you!

## Disclaimer

This tool is intended for personal use with content you have the right to download —
your own uploads, Creative Commons or public-domain videos, or material where the
rights holder has given permission. Downloading content from YouTube may violate
[YouTube's Terms of Service](https://www.youtube.com/t/terms) and copyright law in
your country. You are solely responsible for how you use this software; the author
assumes no liability for misuse.

This project is not affiliated with, endorsed by, or sponsored by YouTube or Google.

## Third-party software

This repository contains no third-party binaries. The dependencies are installed
from PyPI under their own licenses: yt-dlp (Unlicense), rich (MIT) and
static-ffmpeg (see its PyPI page). On first run, `static-ffmpeg` downloads
ffmpeg binaries, which are distributed under the LGPL/GPL.

## License

Released under the [MIT License](LICENSE).
