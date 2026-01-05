# Recipe Collector Bot

🌐 *[Deutsch](README.de.md) | English*

> **Note:** This is a small vibe coding project from a single morning. It solves my personal problem and nothing more. Use at your own risk.

A Telegram bot that extracts cooking recipes from videos and images. Simply send a TikTok video, Instagram Reel, or screenshot - the bot returns the formatted recipe.

## Features

- **Video Analysis**: Extracts recipes from videos (TikTok, Instagram, YouTube, etc.)
- **Image Recognition**: Also works with screenshots and photos
- **Instant Feedback**: Response directly in Telegram chat
- **Multiple Formats**: Export as Markdown (`.md`) or Cooklang (`.cook`)
- **Local Storage**: Optionally save directly to Obsidian vault
- **Cross-Platform**: Works on Android, iOS, Desktop, Web
- **Self-Hosted**: Runs on your own server/NAS

## Quick Start

### 1. Create Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Choose a name (e.g., "My Recipe Bot")
4. Choose a username (e.g., `my_recipe_bot`)
5. Copy the bot token

### 2. Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key

### 3. Your Telegram User ID

1. Open Telegram and search for `@userinfobot`
2. Send any message
3. Copy your user ID (number)

### 4. Installation

#### With Docker (recommended)

```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/recipe-collector.git
cd recipe-collector

# Create configuration
cp config.yaml.example config.yaml
nano config.yaml  # Enter values

# Start
docker compose up -d

# View logs
docker compose logs -f
```

#### Without Docker

```bash
# Clone repository
git clone https://github.com/YOUR_USERNAME/recipe-collector.git
cd recipe-collector

# Prerequisites
# - Python 3.11+
# - ffmpeg

# Virtual environment
python3 -m venv venv
source venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Configuration
cp config.yaml.example config.yaml
nano config.yaml  # Enter values

# Start
python bot.py
```

## Configuration

```yaml
telegram:
  bot_token: "123456:ABC..."  # From @BotFather
  allowed_users:
    - 123456789  # Your user ID

gemini:
  api_key: "AIza..."  # From Google AI Studio
  model: gemini-2.0-flash

# Optional: Local storage
storage:
  enabled: false
  path: /path/to/obsidian/vault/Recipes

# Output format
output:
  format: markdown  # or "cooklang"
```

### Environment Variables

Alternatively, you can use environment variables:

```yaml
telegram:
  bot_token: ${TELEGRAM_BOT_TOKEN}

gemini:
  api_key: ${GEMINI_API_KEY}
```

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export GEMINI_API_KEY="AIza..."
```

## Usage

### Send Video

1. Find a recipe video (TikTok, Instagram, etc.)
2. Share the video to your bot (or download and send directly)
3. The bot responds with the extracted recipe

### Send Link

1. Copy the video URL
2. Send the URL to the bot
3. The bot downloads the video and extracts the recipe

**Note:** Downloading TikTok/Instagram links is often unreliable. If you have problems: Download the video on your phone and send it directly.

### Send Image

1. Take a screenshot of a recipe
2. Send the image to the bot
3. The bot extracts the recipe

### Buttons

After each recipe, buttons appear:

- **📄 As Markdown** / **📄 As Cooklang**: Sends the recipe as file for download (format depends on config)
- **💾 Save**: Saves to Obsidian vault (if configured)

### Output Formats

The bot supports two output formats, configurable via `output.format`:

#### Markdown (default)

Standard Markdown format (`.md`), optimized for Obsidian:

```markdown
**Source:** [Creator](https://example.com)
**Servings:** 4 servings
**Time:** Prep: 15 min | Cook: 30 min

## Ingredients

- 400g Spaghetti
- 200g Guanciale

## Instructions

1. Cook pasta in salted water
2. Fry guanciale until crispy
```

#### Cooklang

[Cooklang](https://cooklang.org/) format (`.cook`) for use with Cooklang apps or the Obsidian Cooklang plugin:

```
>> source: https://example.com
>> servings: 4 servings
>> total time: 45 min
>> tags: italian, pasta

-- Ingredients --

-- @Spaghetti{400%g}
-- @Guanciale{200%g}

-- Instructions --

Cook @pasta{} in salted water.

Fry @guanciale{} until crispy.
```

To enable Cooklang output:

```yaml
output:
  format: cooklang
```

## Extraction Logic

The bot uses different data sources depending on input. Here's an overview of all scenarios:

### Input Types

| Input | What happens |
|-------|--------------|
| **Video URL** (TikTok, YouTube, Instagram) | Download video + metadata → Gemini |
| **Webpage URL** (Recipe blog) | Parse JSON-LD schema or text → Gemini |
| **Video file** (sent directly) | Video → Gemini |
| **Image/Screenshot** | Image → Gemini |
| **Image + URL** (as caption) | Image + webpage text → Gemini |

### Video Platforms (TikTok, YouTube, Instagram, Facebook)

```
URL received
    │
    ▼
┌─────────────────────────────┐
│  1. Extract metadata        │  ← yt-dlp --dump-json
│     • Title                 │
│     • Description           │
│     • Creator/Uploader      │
│     • Tags                  │
│     • Subtitles (YouTube)   │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  2. Download video          │  ← yt-dlp
└─────────────────────────────┘
    │
    ├── Success ───────────────────────────────────────┐
    │                                                   ▼
    │                              ┌─────────────────────────────────┐
    │                              │  Send video + ALL metadata      │
    │                              │  to Gemini                      │
    │                              │                                 │
    │                              │  Gemini receives:               │
    │                              │  • Video file (visual)          │
    │                              │  • Subtitles (highest priority) │
    │                              │  • Description (ingredients!)   │
    │                              │  • Title, Creator, Tags         │
    │                              └─────────────────────────────────┘
    │
    └── Failed ────────────────────────────────────────┐
                                                        ▼
                                   ┌─────────────────────────────────┐
                                   │  Metadata available?            │
                                   └─────────────────────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                    Yes (Description              No
                    or Title)                        │
                          │                          │
                          ▼                          ▼
           ┌──────────────────────┐    ┌──────────────────────┐
           │  ONLY metadata to    │    │  Extract webpage     │
           │  Gemini (no video)   │    │  text (fallback)     │
           │                      │    └──────────────────────┘
           │  → Recipe from       │
           │    description       │
           └──────────────────────┘
```

**Source prioritization in case of conflicts:**
1. Subtitles/Captions (most accurate source for spoken quantities)
2. Video description (often contains complete ingredient lists)
3. Video content (visual information)
4. Webpage text (context)

### Recipe Websites (Blogs, AllRecipes, etc.)

```
URL received
    │
    ▼
┌─────────────────────────────┐
│  Download HTML              │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  Search for JSON-LD schema  │  ← <script type="application/ld+json">
│  (@type: "Recipe")          │
└─────────────────────────────┘
    │
    ├── Schema found ──────────────────────────────────┐
    │                                                   ▼
    │                              ┌─────────────────────────────────┐
    │                              │  Parse directly (no Gemini!)   │
    │                              │                                 │
    │                              │  Extracts:                      │
    │                              │  • recipeIngredient             │
    │                              │  • recipeInstructions           │
    │                              │  • prepTime, cookTime           │
    │                              │  • recipeYield (servings)       │
    │                              │  • author, keywords             │
    │                              │                                 │
    │                              │  → 90%+ accuracy!               │
    │                              └─────────────────────────────────┘
    │
    └── No schema ─────────────────────────────────────┐
                                                        ▼
                                   ┌─────────────────────────────────┐
                                   │  Extract text and send to       │
                                   │  Gemini                         │
                                   └─────────────────────────────────┘
```

**Why JSON-LD is so good:**
Most recipe websites have structured data for Google/Pinterest. These are already perfectly formatted - no AI interpretation needed!

### Image/Screenshot

```
Image received
    │
    ├── With URL as caption? ──────────────────────────┐
    │         │                                         ▼
    │         │                    ┌─────────────────────────────────┐
    │         │                    │  Fetch webpage text             │
    │         │                    └─────────────────────────────────┘
    │         │                                         │
    │         └─────────────────────────────────────────┤
    │                                                   ▼
    ▼                              ┌─────────────────────────────────┐
┌─────────────────────────────┐    │  Send image + webpage text      │
│  Only image to Gemini       │    │  to Gemini                      │
└─────────────────────────────┘    └─────────────────────────────────┘
```

### Video File (sent directly)

```
Video received (Telegram upload)
    │
    ▼
┌─────────────────────────────┐
│  Send video to Gemini       │
│                             │
│  No metadata available!     │
│  Visual analysis only       │
└─────────────────────────────┘
```

**Tip:** Directly sent videos lack description/subtitles. If the original video has a detailed description, better send the link!

### Data Model

Each extracted recipe contains:

| Field | Description | Source |
|-------|-------------|--------|
| `title` | Recipe name | Title, Video, Image |
| `servings` | Servings | Description, Schema |
| `prep_time` | Preparation time | Schema, Description |
| `cook_time` | Cooking time | Schema, Description |
| `total_time` | Total time | Schema, calculated |
| `difficulty` | easy/medium/hard | Gemini assessment |
| `tags` | Categories | Tags, Keywords, Schema |
| `ingredients` | Ingredient list with quantities | All sources |
| `instructions` | Preparation steps | All sources |
| `equipment` | Required equipment | Video, Description |
| `notes` | Tips, variations | Video, Description |
| `source_url` | Original URL | Input |
| `source_platform` | tiktok/youtube/web/etc. | Detected from URL |
| `creator` | Video creator | Uploader metadata |

### Known Limitations

| Platform | Status | Note |
|----------|--------|------|
| **YouTube** | ✅ Good | Video + subtitles + description |
| **TikTok** | ⚠️ Limited | Video download often blocked, metadata usually OK |
| **Instagram** | ⚠️ Limited | Often requires login, limited metadata |
| **Facebook** | ⚠️ Limited | Similar to Instagram |
| **Recipe Blogs** | ✅ Very good | JSON-LD schema = perfect data |
| **Pinterest** | ⚠️ Limited | Often redirects to original page |

**Workaround for download problems:**
1. Download video in the app (TikTok: "Save", Instagram: third-party app)
2. Send video directly to the bot
3. Optional: Add original URL as caption for context

## Bot Commands

- `/start` - Show help
- `/id` - Show your user ID

## Example Output

```
🍽 Spaghetti Carbonara

⏱ 30 min | 👥 4 servings
🏷 #italian #pasta #quick

📋 Ingredients:
• 400g Spaghetti
• 200g Guanciale
• 4 egg yolks
• 100g Pecorino

👨‍🍳 Instructions:
1. Cook pasta in salted water
2. Fry guanciale until crispy
3. Mix egg yolks with cheese
4. Combine everything

🔗 Source
```

## Systemd Service (for persistent operation)

```ini
# /etc/systemd/system/recipe-bot.service
[Unit]
Description=Recipe Collector Bot
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/recipe-collector
ExecStart=/home/pi/recipe-collector/venv/bin/python bot.py
Restart=on-failure
RestartSec=10
Environment=TELEGRAM_BOT_TOKEN=...
Environment=GEMINI_API_KEY=...

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable recipe-bot
sudo systemctl start recipe-bot
```

## Costs

- **Telegram Bot**: Free
- **Gemini 2.0 Flash**: ~$0.00001 per recipe (practically free)
- **Hosting**: Your own server/NAS/Raspberry Pi

## Troubleshooting

### "Download failed"

TikTok and Instagram often block downloads. Solution:
1. Download video on your phone (with TikTok app or third-party app)
2. Send video directly to the bot

### Bot doesn't respond

1. Check if your user ID is in `allowed_users`
2. Check logs: `docker compose logs -f` or terminal
3. Check if bot token is correct

### Gemini Error

1. Check if API key is correct
2. Check quota: https://aistudio.google.com/app/apikey

## Project Structure

```
recipe-collector/
├── bot.py              # Telegram bot main logic
├── extractor.py        # Gemini AI integration
├── config.py           # Configuration
├── config.yaml.example # English config template
├── config.yaml.de_example # German config template
├── requirements.txt
├── README.md           # English
├── README.de.md        # German
├── Dockerfile
└── docker-compose.yml
```

## License

CC0 (Public Domain)

## Similar Projects

- [Tandoor Recipes](https://github.com/TandoorRecipes/recipes) - Self-hosted Recipe Manager
- [Mealie](https://github.com/mealie-recipes/mealie) - Self-hosted Recipe Manager
- [Cooklang](https://cooklang.org/) - Markup language for recipes
