# Recipe Collector Bot

Ein Telegram-Bot, der Kochrezepte aus Videos und Bildern extrahiert. Sende einfach ein TikTok-Video, Instagram-Reel oder ein Screenshot - der Bot liefert das formatierte Rezept zurück.

## Features

- **Video-Analyse**: Extrahiert Rezepte aus Videos (TikTok, Instagram, YouTube, etc.)
- **Bild-Erkennung**: Funktioniert auch mit Screenshots und Fotos
- **Sofortiges Feedback**: Antwort direkt im Telegram-Chat
- **Markdown-Export**: Download als `.md` Datei für Obsidian
- **Lokale Speicherung**: Optional direkt im Obsidian Vault speichern
- **Plattformübergreifend**: Funktioniert auf Android, iOS, Desktop, Web
- **Selbst-gehostet**: Läuft auf deinem eigenen Server/NAS

## Schnellstart

### 1. Bot erstellen

1. Öffne Telegram und suche nach `@BotFather`
2. Sende `/newbot`
3. Wähle einen Namen (z.B. "Mein Rezept Bot")
4. Wähle einen Username (z.B. `mein_rezept_bot`)
5. Kopiere den Bot-Token

### 2. Gemini API Key

1. Gehe zu https://aistudio.google.com/app/apikey
2. Klicke auf "Create API Key"
3. Kopiere den Key

### 3. Deine Telegram User-ID

1. Öffne Telegram und suche nach `@userinfobot`
2. Sende eine beliebige Nachricht
3. Kopiere deine User-ID (Zahl)

### 4. Installation

#### Mit Docker (empfohlen)

```bash
# Repository klonen
git clone https://github.com/DEIN_USERNAME/recipe-collector.git
cd recipe-collector

# Konfiguration erstellen
cp config.yaml.example config.yaml
nano config.yaml  # Werte eintragen

# Starten
docker compose up -d

# Logs anzeigen
docker compose logs -f
```

#### Ohne Docker

```bash
# Repository klonen
git clone https://github.com/DEIN_USERNAME/recipe-collector.git
cd recipe-collector

# Voraussetzungen
# - Python 3.11+
# - ffmpeg

# Virtual Environment
python3 -m venv venv
source venv/bin/activate

# Dependencies
pip install -r requirements.txt

# Konfiguration
cp config.yaml.example config.yaml
nano config.yaml  # Werte eintragen

# Starten
python bot.py
```

## Konfiguration

```yaml
telegram:
  bot_token: "123456:ABC..."  # Von @BotFather
  allowed_users:
    - 123456789  # Deine User-ID

gemini:
  api_key: "AIza..."  # Von Google AI Studio
  model: gemini-1.5-flash

# Optional: Lokales Speichern
storage:
  enabled: false
  path: /pfad/zu/obsidian/vault/Rezepte
```

### Umgebungsvariablen

Alternativ kannst du Umgebungsvariablen nutzen:

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

## Nutzung

### Video senden

1. Finde ein Rezept-Video (TikTok, Instagram, etc.)
2. Teile das Video an deinen Bot (oder lade es herunter und sende es direkt)
3. Der Bot antwortet mit dem extrahierten Rezept

### Link senden

1. Kopiere die URL des Videos
2. Sende die URL an den Bot
3. Der Bot lädt das Video herunter und extrahiert das Rezept

**Hinweis:** Das Herunterladen von TikTok/Instagram-Links ist oft unzuverlässig. Bei Problemen: Video auf dem Handy herunterladen und direkt senden.

### Bild senden

1. Mache einen Screenshot von einem Rezept
2. Sende das Bild an den Bot
3. Der Bot extrahiert das Rezept

### Buttons

Nach jedem Rezept erscheinen Buttons:

- **📄 Als Markdown**: Sendet das Rezept als `.md` Datei zum Download
- **💾 Speichern**: Speichert im Obsidian Vault (wenn konfiguriert)

## Bot-Befehle

- `/start` - Hilfe anzeigen
- `/id` - Deine User-ID anzeigen

## Beispiel-Ausgabe

```
🍽 Spaghetti Carbonara

⏱ 30 min | 👥 4 Portionen
🏷 #italienisch #pasta #schnell

📋 Zutaten:
• 400g Spaghetti
• 200g Guanciale
• 4 Eigelb
• 100g Pecorino

👨‍🍳 Zubereitung:
1. Pasta in Salzwasser kochen
2. Guanciale knusprig braten
3. Eigelb mit Käse vermengen
4. Alles zusammenführen

🔗 Quelle
```

## Systemd-Service (für dauerhaften Betrieb)

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

## Kosten

- **Telegram Bot**: Kostenlos
- **Gemini 1.5 Flash**: ~$0.00001 pro Rezept (praktisch kostenlos)
- **Hosting**: Dein eigener Server/NAS/Raspberry Pi

## Troubleshooting

### "Download fehlgeschlagen"

TikTok und Instagram blockieren oft Downloads. Lösung:
1. Video auf dem Handy herunterladen (mit TikTok-App oder Drittanbieter-App)
2. Video direkt an den Bot senden

### "Konnte keine Frames extrahieren"

Stelle sicher dass `ffmpeg` installiert ist:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# Docker: Bereits enthalten
```

### Bot antwortet nicht

1. Prüfe ob deine User-ID in `allowed_users` steht
2. Prüfe die Logs: `docker compose logs -f` oder Terminal
3. Prüfe ob Bot-Token korrekt ist

### Gemini-Fehler

1. Prüfe ob API-Key korrekt ist
2. Prüfe Quota: https://aistudio.google.com/app/apikey

## Projektstruktur

```
recipe-collector/
├── bot.py              # Telegram Bot Hauptlogik
├── extractor.py        # Gemini AI Integration
├── media_handler.py    # Video/Bild-Verarbeitung
├── config.py           # Konfiguration
├── config.yaml.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Lizenz

MIT

## Ähnliche Projekte

- [Tandoor Recipes](https://github.com/TandoorRecipes/recipes) - Self-hosted Recipe Manager
- [Mealie](https://github.com/mealie-recipes/mealie) - Self-hosted Recipe Manager
- [Cooklang](https://cooklang.org/) - Markup-Sprache für Rezepte
