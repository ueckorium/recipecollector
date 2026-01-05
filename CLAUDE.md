# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Recipe Collector Bot is a Telegram bot that extracts cooking recipes from videos, images, and URLs using Google's Gemini AI. It supports multiple video platforms (TikTok, Instagram, YouTube, Facebook) and can parse structured recipe data from websites via JSON-LD schemas.

## Commands

### Running the Bot

```bash
# Without Docker
source venv/bin/activate
python bot.py

# With Docker
docker compose up -d
docker compose logs -f
```

### Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
# Edit config.yaml with your credentials
```

### Dependencies

- Python 3.11+
- ffmpeg (system dependency for video processing)
- yt-dlp (installed via pip, used for video downloads)

## Architecture

### Core Modules

- **bot.py** - Telegram bot handlers using pyTelegramBotAPI. Contains message handlers for videos, images, URLs, and documents. Uses an LRU cache for storing recipes for callback buttons.

- **extractor.py** - Recipe extraction logic. Contains:
  - `extract_recipe_from_video()` - Uploads video to Gemini for analysis
  - `extract_recipe_from_image()` - Sends image to Gemini
  - `extract_recipe_from_url()` - Routes to video download or webpage parsing
  - `extract_recipe_from_webpage()` - Tries JSON-LD schema first, then Gemini
  - `extract_recipe_schema()` - Parses schema.org/Recipe JSON-LD (high accuracy)
  - `download_video_from_url()` - Uses yt-dlp with metadata extraction
  - Formatting functions: `format_recipe_chat()`, `format_recipe_markdown()`, `format_recipe_cooklang()`

- **config.py** - Configuration management with dataclasses. Supports YAML config with environment variable expansion (`${ENV_VAR}` syntax).

### Data Flow

1. **Video URLs**: Extract metadata via yt-dlp → Download video → Send video + metadata to Gemini → Parse JSON response
2. **Webpage URLs**: Try JSON-LD schema parsing first (no AI needed) → Fallback to Gemini text analysis
3. **Direct uploads**: Send directly to Gemini (no metadata available)
4. **If video download fails**: Fallback to metadata-only extraction, then webpage text

### Key Data Structures

- `Recipe` dataclass in extractor.py - Complete recipe with title, ingredients, instructions, times, tags, etc.
- `VideoMetadata` dataclass - Metadata from yt-dlp (title, description, subtitles, uploader)
- `Config` dataclass hierarchy - Typed configuration for telegram, gemini, storage, output format

### Output Formats

- **Markdown** (`.md`) - Optimized for Obsidian
- **Cooklang** (`.cook`) - Recipe markup language with `@ingredient{amount%unit}` syntax

### Security Considerations

- SSRF protection in `_validate_and_resolve_url()` and `_safe_request()` - blocks private IPs, localhost
- DNS rebinding protection - resolves DNS once and uses IP directly
- Argument injection protection in yt-dlp calls (`--` separator)
- Path traversal protection in filename handling
- User whitelist via `allowed_users` config

## Configuration

Config is loaded from `config.yaml`. Required fields:
- `telegram.bot_token` - From @BotFather
- `gemini.api_key` - From Google AI Studio
- `telegram.allowed_users` - List of authorized Telegram user IDs

Optional:
- `storage.enabled` / `storage.path` - Auto-save recipes to filesystem
- `output.format` - "markdown" or "cooklang"
- `prompts.extraction` - Custom extraction prompt for Gemini

Logging level: Set `LOG_LEVEL` environment variable (default: INFO).
