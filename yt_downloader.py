#!/usr/bin/env python3
"""
YT Downloader — an interactive terminal tool for downloading YouTube videos and audio.

Supported platforms:
    Windows  x86-64 / ARM64
    macOS    Intel  / Apple Silicon
    Linux    x86-64 / ARM64 (aarch64)

Requires Python 3.11 or newer (the minimum of current yt-dlp releases).

Dependencies: yt-dlp, rich, static-ffmpeg (provides ffmpeg automatically)
"""

import glob
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
if sys.version_info < MIN_PYTHON:
    sys.stderr.write(
        "YT Downloader requires Python {}.{} or newer — found {}.{}\n".format(
            MIN_PYTHON[0], MIN_PYTHON[1], sys.version_info[0], sys.version_info[1]
        )
    )
    sys.exit(1)


def _setup_console_encoding() -> None:
    """
    Depending on the version, Windows terminals still run a legacy code page
    (e.g. cp1252). Rich prints box-drawing characters, which would otherwise
    crash with a UnicodeEncodeError there. UTF-8 is already the default on
    macOS/Linux.
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
        "Missing dependency: yt-dlp\n"
        "Install it with: {} -m pip install -r requirements.txt\n".format(sys.executable)
    )
    sys.exit(1)

try:
    from rich import box
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        DownloadColumn,
        Progress,
        ProgressColumn,
        SpinnerColumn,
        TaskID,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
    from rich.prompt import Confirm, Prompt
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.stderr.write(
        "Missing dependency: rich\n"
        "Install it with: {} -m pip install -r requirements.txt\n".format(sys.executable)
    )
    sys.exit(1)


console = Console()

ACCENT = "cyan"


# ─── Platform detection ───────────────────────────────────────────────────────

def platform_label() -> str:
    """Readable description of OS and architecture, e.g. 'Linux aarch64'."""
    return "{} {}".format(platform.system(), platform.machine() or "unknown")


def supported_browsers() -> list[str]:
    """
    Browsers yt-dlp can read cookies from on this operating system.
    Safari only exists on macOS — offering it on Windows/Linux would just
    lead to confusing error messages.
    """
    browsers = ["chrome", "edge", "firefox", "chromium", "brave", "opera", "vivaldi"]
    if sys.platform == "darwin":
        browsers.append("safari")
    return browsers


def ffmpeg_install_hint() -> str:
    """Manual install command suited to the current system."""
    if sys.platform == "win32":
        return "winget install Gyan.FFmpeg     (or: choco install ffmpeg)"
    if sys.platform == "darwin":
        return "brew install ffmpeg"
    return (
        "sudo apt install ffmpeg      (Debian / Ubuntu / Raspberry Pi OS)\n"
        "sudo dnf install ffmpeg      (Fedora)\n"
        "sudo pacman -S ffmpeg        (Arch)"
    )


def _ffmpeg_runs() -> bool:
    """
    True if ffmpeg and ffprobe are on the PATH *and actually start*. A binary
    built for another architecture (e.g. 32-bit ARM Linux, or Windows 10 ARM
    without x64 emulation) is found by shutil.which but fails when executed.
    """
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            return False
        try:
            subprocess.run(
                [tool, "-version"], capture_output=True, check=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return True


def ensure_ffmpeg() -> tuple[bool, str]:
    """
    Makes sure ffmpeg and ffprobe can be called.

    Order:
      1. System-wide installation (works on every architecture)
      2. static-ffmpeg — downloads matching binaries on first use for
         win32 / darwin / darwin_arm64 / linux / linux_arm64

    Returns (success, source-or-error-message). A failure is not fatal:
    downloads of single, already muxed formats also work without ffmpeg.
    """
    if _ffmpeg_runs():
        return True, "installed system-wide"

    try:
        import static_ffmpeg
    except ImportError:
        return False, "static-ffmpeg is not installed"

    console.print(
        "[dim]ffmpeg not found — downloading binaries for {} "
        "(one-time, about 100 MB) …[/dim]".format(escape(platform_label()))
    )
    try:
        static_ffmpeg.add_paths(weak=True)
    except Exception as exc:
        # No network, firewall, or no binaries for this architecture
        # (e.g. Windows ARM64 without x64 emulation).
        return False, "{}: {}".format(type(exc).__name__, exc)

    if _ffmpeg_runs():
        return True, "provided by static-ffmpeg"
    return False, "the downloaded ffmpeg binaries do not run on this system"


# ─── File names and paths (cross-platform) ────────────────────────────────────

# Device names forbidden on Windows — a file "CON.mp4" cannot be created there,
# regardless of its extension.
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_WINDOWS_RESERVED |= {"COM{}".format(i) for i in range(1, 10)}
_WINDOWS_RESERVED |= {"LPT{}".format(i) for i in range(1, 10)}

# Characters that are forbidden on Windows and at least troublesome on
# macOS/Linux (":" causes chaos in Finder, "/" is a separator everywhere).
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _truncate_bytes(name: str, max_bytes: int = 150) -> str:
    """
    Truncates to `max_bytes` UTF-8 bytes. Most file systems (ext4, APFS, NTFS)
    limit a path component to 255 bytes — with Japanese or emoji titles that
    is far fewer characters than bytes.
    """
    encoded = name.encode("utf-8")
    if len(encoded) <= max_bytes:
        return name
    return encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip()


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """
    Turns an arbitrary video title or user input into a file name that is
    equally valid on Windows, macOS and Linux.
    """
    cleaned = _ILLEGAL_CHARS.sub("_", name)
    # "%" collides with yt-dlp's output templates (e.g. "%(ext)s").
    cleaned = cleaned.replace("%", "_")
    # Windows silently strips trailing dots and spaces — the displayed path
    # would then no longer match the real file.
    cleaned = cleaned.strip().rstrip(". ")
    cleaned = _truncate_bytes(cleaned).rstrip(". ")

    if not cleaned:
        return fallback
    if cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    return cleaned


def normalize_path_input(raw: str) -> str:
    """
    Cleans up a path that was typed by hand or dragged into the terminal.

    Windows' "Copy as path" wraps the path in quotes; the macOS/Linux terminal
    escapes spaces with a backslash on drag & drop (on Windows the backslash
    is the path separator itself).
    """
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    if sys.platform != "win32":
        text = text.replace("\\ ", " ")
    # Resolves %USERPROFILE% (Windows) or $HOME (POSIX).
    return os.path.expandvars(text).strip()


# ─── UI helpers ───────────────────────────────────────────────────────────────

def format_duration(seconds) -> str:
    """Formats a duration as m:ss, or h:mm:ss for anything over an hour."""
    minutes, secs = divmod(int(seconds or 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "{}:{:02d}:{:02d}".format(hours, minutes, secs)
    return "{}:{:02d}".format(minutes, secs)


def show_header() -> None:
    """Shows the app header in the terminal."""
    console.print()
    console.print(Panel.fit(
        "[bold {a}]YT Downloader[/bold {a}]\n"
        "[white]Download YouTube videos & audio, right from your terminal[/white]\n"
        "[dim]{p}[/dim]".format(a=ACCENT, p=escape(platform_label())),
        box=box.DOUBLE,
        border_style=ACCENT,
        padding=(1, 4),
    ))
    console.print()


def show_step(number: int, title: str) -> None:
    """Prints a section divider such as 'Step 2 · Format'."""
    console.print(Rule(
        "[bold {a}]Step {n}[/bold {a}] [dim]·[/dim] [bold]{t}[/bold]".format(
            a=ACCENT, n=number, t=title
        ),
        style="dim",
        align="left",
    ))


def show_video_info(info: dict) -> None:
    """Shows title, channel and duration of the video that was found."""
    title = escape(info.get("title") or "Unknown")
    uploader = escape(info.get("uploader") or "Unknown")
    duration = format_duration(info.get("duration"))

    console.print(Panel(
        "[bold white]{}[/bold white]\n"
        "[dim]Channel:[/dim] {}   [dim]Duration:[/dim] {}".format(title, uploader, duration),
        title="[green]Video found[/green]",
        title_align="left",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()


def choice_table(column_title: str, labels: list[str]) -> Table:
    """A numbered selection list with consistent styling."""
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 2))
    table.add_column("No.", style=ACCENT, width=4)
    table.add_column(column_title, style="green")
    for i, label in enumerate(labels, start=1):
        table.add_row(str(i), label)
    return table


# ─── Browser cookie selection ─────────────────────────────────────────────────

def ask_browser() -> str:
    """
    Shows the browsers supported on this system and returns the chosen name.
    yt-dlp then reads the cookies directly from the local browser profile.
    """
    browsers = supported_browsers()

    console.print()
    console.print(Panel(
        "[yellow]YouTube blocked the request (bot protection).[/yellow]\n"
        "Fix: pass along the cookies of a browser you are logged in with.\n"
        "[dim]The browser must be installed on this device and logged in to YouTube.[/dim]",
        title="[yellow]Authentication required[/yellow]",
        title_align="left",
        border_style="yellow",
        padding=(1, 2),
    ))
    console.print()

    console.print("[bold]Which browser do you want to use?[/bold]")
    console.print(choice_table("Browser", [b.capitalize() for b in browsers]))
    console.print()

    choice = Prompt.ask(
        "[{}]Choose browser[/{}]".format(ACCENT, ACCENT),
        choices=[str(i) for i in range(1, len(browsers) + 1)],
        default="1",
    )

    return browsers[int(choice) - 1]


# ─── Format and quality selection ─────────────────────────────────────────────

def build_base_opts(browser: str | None = None) -> dict:
    """Builds the shared yt-dlp base options, optionally with browser cookies."""
    opts: dict = {"quiet": True, "no_warnings": True}
    if browser:
        # Tuple format: (browser, profile, keyring, container) — only the name is needed
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def fetch_video_info(url: str, browser: str | None = None) -> dict:
    """
    Fetches metadata and available formats from YouTube without downloading.
    If `browser` is set, its cookies are used for authentication.
    """
    opts = build_base_opts(browser)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not info:
        raise yt_dlp.utils.DownloadError("No video information received.")
    # For playlists and channels yt-dlp returns a collection — we take the
    # first entry so that format selection and title work.
    if info.get("_type") in ("playlist", "multi_video") and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise yt_dlp.utils.DownloadError("The playlist contains no playable videos.")
        info = entries[0]
    return info


def ask_download_type() -> str:
    """Asks whether a video (mp4) or audio only (mp3) is wanted."""
    console.print("[dim]video → MP4 (H.264/AAC)   audio → MP3 (192 kbit/s)[/dim]")
    return Prompt.ask(
        "[{}]Choose format[/{}]".format(ACCENT, ACCENT),
        choices=["video", "audio"],
        default="video",
    )


def ask_video_quality(info: dict) -> str:
    """
    Lists the available video resolutions and lets the user pick one.
    Returns a yt-dlp format selector string.
    """
    formats = info.get("formats", [])

    heights = sorted(
        {f["height"] for f in formats if f.get("vcodec") != "none" and f.get("height")},
        reverse=True,
    )

    if not heights:
        return "bestvideo+bestaudio/best"

    labels = ["{}p".format(h) + ("  (best)" if i == 0 else "") for i, h in enumerate(heights)]
    console.print("[bold]Available resolutions:[/bold]")
    console.print(choice_table("Resolution", labels))
    console.print()

    choice = Prompt.ask(
        "[{}]Choose resolution[/{}]".format(ACCENT, ACCENT),
        choices=[str(i) for i in range(1, len(heights) + 1)],
        default="1",
    )

    selected = heights[int(choice) - 1]
    return "bestvideo[height<={h}]+bestaudio/best[height<={h}]".format(h=selected)


# ─── Path and file name input ─────────────────────────────────────────────────

def ask_output_path() -> Path:
    """Asks for the target folder and creates it if necessary."""
    default = str(Path.home() / "Downloads")
    raw = Prompt.ask("[{}]Save to[/{}]".format(ACCENT, ACCENT), default=default)
    text = normalize_path_input(raw) or default

    try:
        path = Path(text).expanduser().resolve()
    except (OSError, ValueError) as exc:
        console.print("[red]Invalid path: {}[/red]".format(escape(str(exc))))
        sys.exit(1)

    if not path.exists():
        if Confirm.ask("[yellow]Folder '{}' does not exist. Create it?[/yellow]".format(escape(str(path)))):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                console.print("[red]Could not create folder: {}[/red]".format(escape(str(exc))))
                sys.exit(1)
        else:
            console.print("[red]Cancelled.[/red]")
            sys.exit(0)

    return path


def ask_filename(default_title: str) -> str:
    """Asks for the file name (without extension) and makes it safe for the file system."""
    answer = Prompt.ask(
        "[{}]File name (without extension)[/{}]".format(ACCENT, ACCENT),
        default=sanitize_filename(default_title),
    )
    # Free-form input is sanitized too — a typed "a/b" or "CON" would
    # otherwise fail silently depending on the operating system.
    return sanitize_filename(answer)


# ─── Download ─────────────────────────────────────────────────────────────────

# Re-encode to H.264/AAC so every device can play the file.
# The preferred avc1 format selector already avoids re-encoding in most cases,
# but this guarantees compatibility when only VP9 or AV1 streams are available.
#
# -pix_fmt yuv420p is essential here: YouTube serves HDR videos as 10-bit VP9
# (profile 2) or AV1. Without this line libx264 would turn them into H.264
# "High 10", which hardly any hardware decoder (smart TV, phone, QuickTime)
# can play — exactly what this is meant to avoid.
H264_FFMPEG_ARGS = (
    "-c:v", "libx264", "-crf", "20", "-preset", "fast",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "192k",
    "-movflags", "+faststart",
)

# Post-processors worth showing to the user, and what to call them. Anything
# else (metadata, file moves) finishes instantly and would only flicker.
_POSTPROCESSOR_LABELS = {
    "Merger":           "Merging video + audio",
    "VideoConvertor":   "Finalizing MP4",
    "ExtractAudio":     "Converting to MP3",
}


class _TransferOnly(ProgressColumn):
    """Wraps a column so it renders only for downloads, not for post-processing rows."""

    def __init__(self, column: ProgressColumn) -> None:
        super().__init__()
        self._column = column

    def render(self, task):
        if task.fields.get("processing"):
            return Text("")
        return self._column.render(task)


class DownloadProgress:
    """
    Renders yt-dlp's download and post-processing progress as rich progress bars.

    Use as a context manager and pass `progress_hook` / `postprocessor_hook` to
    yt-dlp. Video and audio streams download one after another, so each file
    gets its own bar; merging and re-encoding show a spinner because ffmpeg
    reports no progress and the step can take minutes.
    """

    def __init__(self) -> None:
        self._progress = Progress(
            SpinnerColumn(style=ACCENT),
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=None, complete_style=ACCENT, finished_style="green"),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            _TransferOnly(DownloadColumn()),
            _TransferOnly(TransferSpeedColumn()),
            _TransferOnly(TimeRemainingColumn()),
            console=console,
        )
        self._downloads: dict[str, TaskID] = {}
        self._processing: dict[str, TaskID] = {}
        self._count = 0

    def __enter__(self) -> "DownloadProgress":
        self._progress.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._progress.stop()

    def progress_hook(self, d: dict) -> None:
        """yt-dlp calls this repeatedly while a file is downloading."""
        key = d.get("filename") or ""
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return

        task_id = self._downloads.get(key)
        if task_id is None:
            self._count += 1
            task_id = self._progress.add_task(
                "Downloading {}".format(self._count), total=None
            )
            self._downloads[key] = task_id

        # Both totals can be missing (live or chunked streams) — the bar then
        # stays indeterminate. The estimate may change while downloading.
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes") or 0

        if status == "finished":
            size = total or downloaded or 1
            self._progress.update(task_id, total=size, completed=size)
        else:
            self._progress.update(task_id, total=total, completed=downloaded)

    def postprocessor_hook(self, d: dict) -> None:
        """yt-dlp calls this when a post-processing step starts and ends."""
        name = d.get("postprocessor")
        label = _POSTPROCESSOR_LABELS.get(name)
        if not label:
            return

        status = d.get("status")
        if status == "started":
            self._processing[name] = self._progress.add_task(label, total=None, processing=True)
        elif status == "finished" and name in self._processing:
            self._progress.update(self._processing[name], total=1, completed=1)


def build_ydl_opts(
    format_selector: str,
    output_template: str,
    is_audio: bool,
    browser: str | None = None,
    progress: DownloadProgress | None = None,
) -> dict:
    """Builds the complete yt-dlp options for the download."""
    opts = build_base_opts(browser)
    opts.update({
        "format":      format_selector,
        "outtmpl":     output_template,
        "quiet":       True,
        "noprogress":  True,
        "no_warnings": True,
    })
    if progress is not None:
        opts["progress_hooks"] = [progress.progress_hook]
        opts["postprocessor_hooks"] = [progress.postprocessor_hook]

    if is_audio:
        opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
    else:
        opts["merge_output_format"] = "mp4"
        # The merger only runs when video and audio are downloaded separately
        # and joined afterwards. If yt-dlp picks an already muxed format
        # instead (e.g. a single .webm), the file would otherwise stay
        # unconverted — the VideoConvertor covers exactly that case. For a
        # file that already is mp4 it skips itself.
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
    Determines what the finished file is really called after all post-processors.

    Predicting the extension goes wrong: depending on the chosen format the
    merger, the converter or neither applies. yt-dlp records the final path
    in `requested_downloads`.
    """
    if isinstance(info, dict):
        for entry in info.get("requested_downloads") or []:
            candidate = entry.get("filepath")
            if candidate and Path(candidate).exists():
                return Path(candidate)

    # Fallback: search the target folder for "<name>.*". glob.escape protects
    # against special characters such as "[" in the file name.
    matches = [Path(m) for m in glob.glob(glob.escape(str(output_path / filename)) + ".*")]
    if not matches:
        return None
    # Ignore intermediate files (.part, .ytdl, .f137), take the largest real file
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
    """Performs the actual download and returns the created file."""
    # os.fspath instead of string concatenation: yields the correct separator
    # on every OS ("\" on Windows, "/" elsewhere).
    template = os.fspath(output_path / filename) + ".%(ext)s"

    with DownloadProgress() as progress:
        opts = build_ydl_opts(format_selector, template, is_audio, browser, progress)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

    return _resolve_output_file(info, output_path, filename)


# ─── Main program ─────────────────────────────────────────────────────────────

def main() -> None:
    show_header()

    # Prepare ffmpeg (needed for HD merging and MP3 extraction)
    ffmpeg_ok, ffmpeg_source = ensure_ffmpeg()
    if ffmpeg_ok:
        console.print("[dim]ffmpeg: {}[/dim]".format(escape(ffmpeg_source)))
    else:
        console.print(Panel(
            "[yellow]ffmpeg is not available.[/yellow]\n"
            "[dim]Reason: {}[/dim]\n\n"
            "HD videos (separate video/audio streams) and MP3 downloads\n"
            "do not work without ffmpeg. Manual installation:\n\n"
            "[{}]{}[/{}]".format(escape(ffmpeg_source), ACCENT, escape(ffmpeg_install_hint()), ACCENT),
            title="[yellow]Notice[/yellow]",
            title_align="left",
            border_style="yellow",
            padding=(1, 2),
        ))
    console.print()

    # Step 1: URL
    show_step(1, "Video URL")
    url = Prompt.ask("[{}]YouTube URL[/{}]".format(ACCENT, ACCENT)).strip()
    if not url:
        console.print("[red]No URL given.[/red]")
        sys.exit(1)
    console.print()

    # Fetch video metadata — offer the browser cookie fallback on failure
    browser: str | None = None
    console.print("[dim]Fetching video information …[/dim]")
    try:
        info = fetch_video_info(url)
    except yt_dlp.utils.DownloadError:
        # First attempt failed (most common cause: YouTube bot protection)
        # → offer browser cookies as a fallback
        browser = ask_browser()
        console.print(
            "\n[dim]Fetching video information with {} cookies …[/dim]".format(browser.capitalize())
        )
        try:
            info = fetch_video_info(url, browser)
        except yt_dlp.utils.DownloadError as e2:
            console.print("\n[red]Error: {}[/red]".format(escape(str(e2))))
            console.print(
                "[dim]Make sure you are logged in to YouTube in this browser.[/dim]"
            )
            sys.exit(1)

    show_video_info(info)

    # Step 2: video or audio?
    show_step(2, "Format")
    download_type = ask_download_type()
    is_audio = download_type == "audio"
    console.print()

    step = 3

    # Step 3 (video only): choose quality
    if is_audio:
        format_selector = "bestaudio/best"
    else:
        show_step(step, "Resolution")
        format_selector = ask_video_quality(info)
        console.print()
        step += 1

    # Target folder
    show_step(step, "Destination")
    output_path = ask_output_path()
    console.print()
    step += 1

    # File name
    show_step(step, "File name")
    filename = ask_filename(info.get("title") or "download")
    console.print()

    # Download
    console.print(Rule("[bold green]Download[/bold green]", style="green"))
    console.print()

    try:
        result = download(url, format_selector, output_path, filename, is_audio, browser)
    except yt_dlp.utils.DownloadError as e:
        console.print("\n[red]Download failed: {}[/red]".format(escape(str(e))))
        if not ffmpeg_ok:
            console.print("[dim]Likely cause: ffmpeg is missing. Install it with:[/dim]")
            console.print("[{}]{}[/{}]".format(ACCENT, escape(ffmpeg_install_hint()), ACCENT))
        sys.exit(1)

    if result is None:
        # The download reported success, but there is no file in the target folder.
        console.print()
        console.print(Panel(
            "[yellow]The download finished, but no file was found.[/yellow]\n"
            "[dim]Expected in: {}[/dim]".format(escape(str(output_path))),
            border_style="yellow",
            padding=(1, 2),
        ))
        sys.exit(1)

    size_mb = result.stat().st_size / (1024 * 1024)
    console.print()
    console.print(Panel(
        "[bold green]Saved successfully![/bold green]\n"
        "[white]{}[/white]\n"
        "[dim]{:.1f} MB[/dim]".format(escape(str(result)), size_mb),
        border_style="green",
        padding=(1, 2),
    ))
    console.print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl-C should not leave a traceback (or, on Windows, a half-drawn
        # rich frame).
        console.print("\n[dim]Cancelled.[/dim]")
        sys.exit(130)
    except EOFError:
        # Ctrl-D, or exhausted input with piped stdin.
        console.print("\n[dim]Input ended — cancelled.[/dim]")
        sys.exit(130)
