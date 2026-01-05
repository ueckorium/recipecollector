"""Verarbeitet Medien: Downloads und Frame-Extraktion."""

import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def is_url(text: str) -> bool:
    """Prüft ob ein Text eine URL ist."""
    if not text:
        return False
    url_pattern = r"https?://[^\s]+"
    return bool(re.match(url_pattern, text.strip()))


def extract_url(text: str) -> str | None:
    """Extrahiert die erste URL aus einem Text."""
    if not text:
        return None
    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None


def download_video(url: str, output_dir: Path) -> Path | None:
    """
    Lädt ein Video von einer URL herunter.

    Verwendet yt-dlp für TikTok/Instagram/YouTube.
    WARNUNG: TikTok und Instagram sind oft unzuverlässig!
    """
    try:
        output_template = str(output_dir / "video.%(ext)s")

        result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "--max-filesize", "50M",
                "-o", output_template,
                "--print", "filename",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.warning(f"yt-dlp fehlgeschlagen: {result.stderr}")
            return None

        downloaded_file = Path(result.stdout.strip())
        if downloaded_file.exists():
            logger.info(f"Video heruntergeladen: {downloaded_file}")
            return downloaded_file

    except subprocess.TimeoutExpired:
        logger.error("yt-dlp Timeout")
    except FileNotFoundError:
        logger.error("yt-dlp nicht installiert")
    except Exception as e:
        logger.error(f"Download-Fehler: {e}")

    return None


def get_video_frames(video_path: Path, num_frames: int = 5) -> list[Path]:
    """
    Extrahiert mehrere Frames aus einem Video für die AI-Analyse.
    Frames werden gleichmäßig über das Video verteilt.
    """
    # Hole Video-Dauer
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        duration = 60.0  # Fallback

    frames = []
    temp_dir = Path(tempfile.mkdtemp())

    for i in range(num_frames):
        timestamp = (duration / (num_frames + 1)) * (i + 1)
        frame_path = temp_dir / f"frame_{i:02d}.jpg"

        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    "-y",
                    str(frame_path),
                ],
                capture_output=True,
                timeout=30,
            )

            if frame_path.exists() and frame_path.stat().st_size > 0:
                frames.append(frame_path)
        except subprocess.TimeoutExpired:
            logger.warning(f"Frame-Extraktion Timeout bei {timestamp}s")

    return frames


def is_video_file(path: Path) -> bool:
    """Prüft ob eine Datei ein Video ist."""
    video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp"}
    return path.suffix.lower() in video_extensions


def is_image_file(path: Path) -> bool:
    """Prüft ob eine Datei ein Bild ist."""
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
    return path.suffix.lower() in image_extensions
