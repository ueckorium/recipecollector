#!/usr/bin/env python3
"""Lokaler Test für Rezept-Extraktion."""

import sys
from pathlib import Path

from config import load_config
from extractor import (
    extract_recipe_from_video,
    extract_recipe_from_image,
    extract_recipe_from_url,
    format_recipe_chat,
    format_recipe_markdown,
)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_extract.py <video_or_image> [source_url]")
        print("  python test_extract.py <url>")
        print()
        print("Examples:")
        print("  python test_extract.py video.mp4")
        print("  python test_extract.py video.mp4 https://tiktok.com/...")
        print("  python test_extract.py https://example.com/recipe")
        sys.exit(1)

    arg = sys.argv[1]
    config = load_config()

    # Prüfe ob es eine URL ist
    if arg.startswith("http://") or arg.startswith("https://"):
        print(f"Verarbeite URL: {arg}")
        print()
        recipe = extract_recipe_from_url(config, arg)
    else:
        file_path = Path(arg)
        source_url = sys.argv[2] if len(sys.argv) > 2 else None

        if not file_path.exists():
            print(f"Datei nicht gefunden: {file_path}")
            sys.exit(1)

        # Typ erkennen
        suffix = file_path.suffix.lower()
        is_video = suffix in [".mp4", ".mov", ".avi", ".mkv", ".webm"]
        is_image = suffix in [".jpg", ".jpeg", ".png", ".gif", ".webp"]

        if not (is_video or is_image):
            print(f"Unbekannter Dateityp: {suffix}")
            sys.exit(1)

        print(f"Verarbeite: {file_path}")
        if source_url:
            print(f"Quelle: {source_url}")
        print()

        if is_video:
            recipe = extract_recipe_from_video(config, file_path, source_url)
        else:
            recipe = extract_recipe_from_image(config, file_path, source_url)

    print("=== Chat-Format ===")
    print(format_recipe_chat(recipe))
    print()
    print("=== Markdown ===")
    print(format_recipe_markdown(recipe))


if __name__ == "__main__":
    main()
