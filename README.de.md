# Recipe Collector Bot

🌐 *Deutsch | [English](README.md)*

Ein Telegram-Bot, der Kochrezepte aus Videos und Bildern extrahiert. Sende einfach ein TikTok-Video, Instagram-Reel oder ein Screenshot - der Bot liefert das formatierte Rezept zurück.

## Features

- **Video-Analyse**: Extrahiert Rezepte aus Videos (TikTok, Instagram, YouTube, etc.)
- **Bild-Erkennung**: Funktioniert auch mit Screenshots und Fotos
- **Sofortiges Feedback**: Antwort direkt im Telegram-Chat
- **Mehrere Formate**: Export als Markdown (`.md`) oder Cooklang (`.cook`)
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

# Konfiguration erstellen (deutsche Version)
cp config.yaml.de_example config.yaml
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

# Konfiguration (deutsche Version)
cp config.yaml.de_example config.yaml
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
  model: gemini-2.0-flash

# Optional: Lokales Speichern
storage:
  enabled: false
  path: /pfad/zu/obsidian/vault/Rezepte

# Ausgabeformat
output:
  format: markdown  # oder "cooklang"
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

### Deutsche Rezept-Ausgabe

Für deutsche Rezepte nutze `config.yaml.de_example` als Vorlage. Diese enthält einen deutschen Extraction-Prompt, der Rezepte auf Deutsch ausgibt.

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

- **📄 Als Markdown** / **📄 Als Cooklang**: Sendet das Rezept als Datei zum Download (Format abhängig von Config)
- **💾 Speichern**: Speichert im Obsidian Vault (wenn konfiguriert)

### Ausgabeformate

Der Bot unterstützt zwei Ausgabeformate, konfigurierbar über `output.format`:

#### Markdown (Standard)

Standard Markdown-Format (`.md`), optimiert für Obsidian:

```markdown
**Quelle:** [Creator](https://example.com)
**Portionen:** 4 Portionen
**Zeit:** Vorbereitung: 15 min | Kochen: 30 min

## Zutaten

- 400g Spaghetti
- 200g Guanciale

## Zubereitung

1. Pasta in Salzwasser kochen
2. Guanciale knusprig braten
```

#### Cooklang

[Cooklang](https://cooklang.org/)-Format (`.cook`) zur Verwendung mit Cooklang-Apps oder dem Obsidian Cooklang-Plugin:

```
>> source: https://example.com
>> servings: 4 Portionen
>> total time: 45 min
>> tags: italienisch, pasta

-- Zutaten --

-- @Spaghetti{400%g}
-- @Guanciale{200%g}

-- Zubereitung --

@Pasta{} in Salzwasser kochen.

@Guanciale{} knusprig braten.
```

Für Cooklang-Ausgabe:

```yaml
output:
  format: cooklang
```

## Extraktionslogik

Der Bot nutzt verschiedene Datenquellen je nach Input. Hier eine Übersicht aller Szenarien:

### Eingabetypen

| Eingabe | Was passiert |
|---------|--------------|
| **Video-URL** (TikTok, YouTube, Instagram) | Video + Metadaten herunterladen → Gemini |
| **Webseiten-URL** (Rezept-Blog) | JSON-LD Schema parsen oder Text → Gemini |
| **Video-Datei** (direkt gesendet) | Video → Gemini |
| **Bild/Screenshot** | Bild → Gemini |
| **Bild + URL** (als Caption) | Bild + Webseiten-Text → Gemini |

### Video-Plattformen (TikTok, YouTube, Instagram, Facebook)

```
URL empfangen
    │
    ▼
┌─────────────────────────────┐
│  1. Metadaten extrahieren   │  ← yt-dlp --dump-json
│     • Titel                 │
│     • Beschreibung          │
│     • Creator/Uploader      │
│     • Tags                  │
│     • Untertitel (YouTube)  │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  2. Video herunterladen     │  ← yt-dlp
└─────────────────────────────┘
    │
    ├── Erfolg ──────────────────────────────────────┐
    │                                                 ▼
    │                              ┌─────────────────────────────────┐
    │                              │  Video + ALLE Metadaten         │
    │                              │  an Gemini senden               │
    │                              │                                 │
    │                              │  Gemini bekommt:                │
    │                              │  • Video-Datei (visuell)        │
    │                              │  • Untertitel (höchste Prio)    │
    │                              │  • Beschreibung (Zutaten!)      │
    │                              │  • Titel, Creator, Tags         │
    │                              └─────────────────────────────────┘
    │
    └── Fehlgeschlagen ──────────────────────────────┐
                                                      ▼
                                   ┌─────────────────────────────────┐
                                   │  Metadaten vorhanden?           │
                                   └─────────────────────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                    Ja (Beschreibung              Nein
                    oder Titel)                      │
                          │                          │
                          ▼                          ▼
           ┌──────────────────────┐    ┌──────────────────────┐
           │  NUR Metadaten an    │    │  Webseiten-Text      │
           │  Gemini (ohne Video) │    │  extrahieren         │
           │                      │    │  (Fallback)          │
           │  → Rezept aus        │    └──────────────────────┘
           │    Beschreibung      │
           └──────────────────────┘
```

**Quellen-Priorisierung bei Konflikten:**
1. Untertitel/Captions (genaueste Quelle für gesprochene Mengen)
2. Video-Beschreibung (oft vollständige Zutatenlisten)
3. Video-Inhalt (visuelle Informationen)
4. Webseiten-Text (Kontext)

### Rezept-Webseiten (Blogs, Chefkoch, etc.)

```
URL empfangen
    │
    ▼
┌─────────────────────────────┐
│  HTML herunterladen         │
└─────────────────────────────┘
    │
    ▼
┌─────────────────────────────┐
│  JSON-LD Schema suchen      │  ← <script type="application/ld+json">
│  (@type: "Recipe")          │
└─────────────────────────────┘
    │
    ├── Schema gefunden ─────────────────────────────┐
    │                                                 ▼
    │                              ┌─────────────────────────────────┐
    │                              │  Direkt parsen (ohne Gemini!)  │
    │                              │                                 │
    │                              │  Extrahiert:                    │
    │                              │  • recipeIngredient             │
    │                              │  • recipeInstructions           │
    │                              │  • prepTime, cookTime           │
    │                              │  • recipeYield (Portionen)      │
    │                              │  • author, keywords             │
    │                              │                                 │
    │                              │  → 90%+ Genauigkeit!            │
    │                              └─────────────────────────────────┘
    │
    └── Kein Schema ─────────────────────────────────┐
                                                      ▼
                                   ┌─────────────────────────────────┐
                                   │  Text extrahieren und an        │
                                   │  Gemini senden                  │
                                   └─────────────────────────────────┘
```

**Warum JSON-LD so gut ist:**
Die meisten Rezept-Webseiten haben strukturierte Daten für Google/Pinterest. Diese sind bereits perfekt formatiert - keine KI-Interpretation nötig!

### Bild/Screenshot

```
Bild empfangen
    │
    ├── Mit URL als Caption? ────────────────────────┐
    │         │                                       ▼
    │         │                    ┌─────────────────────────────────┐
    │         │                    │  Webseiten-Text abrufen         │
    │         │                    └─────────────────────────────────┘
    │         │                                       │
    │         └───────────────────────────────────────┤
    │                                                 ▼
    ▼                              ┌─────────────────────────────────┐
┌─────────────────────────────┐    │  Bild + Webseiten-Text          │
│  Nur Bild an Gemini         │    │  an Gemini senden               │
└─────────────────────────────┘    └─────────────────────────────────┘
```

### Video-Datei (direkt gesendet)

```
Video empfangen (Telegram-Upload)
    │
    ▼
┌─────────────────────────────┐
│  Video an Gemini senden     │
│                             │
│  Keine Metadaten verfügbar! │
│  Nur visuelle Analyse       │
└─────────────────────────────┘
```

**Tipp:** Bei direkt gesendeten Videos fehlen Beschreibung/Untertitel. Wenn das Original-Video eine detaillierte Beschreibung hat, besser den Link senden!

### Datenmodell

Jedes extrahierte Rezept enthält:

| Feld | Beschreibung | Quelle |
|------|--------------|--------|
| `title` | Rezeptname | Titel, Video, Bild |
| `servings` | Portionen | Beschreibung, Schema |
| `prep_time` | Vorbereitungszeit | Schema, Beschreibung |
| `cook_time` | Kochzeit | Schema, Beschreibung |
| `total_time` | Gesamtzeit | Schema, berechnet |
| `difficulty` | einfach/mittel/schwer | Gemini-Einschätzung |
| `tags` | Kategorien | Tags, Keywords, Schema |
| `ingredients` | Zutatenliste mit Mengen | Alle Quellen |
| `instructions` | Zubereitungsschritte | Alle Quellen |
| `equipment` | Benötigte Geräte | Video, Beschreibung |
| `notes` | Tipps, Variationen | Video, Beschreibung |
| `source_url` | Original-URL | Input |
| `source_platform` | tiktok/youtube/web/etc. | Erkannt aus URL |
| `creator` | Video-Ersteller | Uploader-Metadaten |

### Bekannte Einschränkungen

| Plattform | Status | Anmerkung |
|-----------|--------|-----------|
| **YouTube** | ✅ Gut | Video + Untertitel + Beschreibung |
| **TikTok** | ⚠️ Eingeschränkt | Video-Download oft blockiert, Metadaten meist OK |
| **Instagram** | ⚠️ Eingeschränkt | Erfordert oft Login, Metadaten limitiert |
| **Facebook** | ⚠️ Eingeschränkt | Ähnlich wie Instagram |
| **Rezept-Blogs** | ✅ Sehr gut | JSON-LD Schema = perfekte Daten |
| **Pinterest** | ⚠️ Eingeschränkt | Leitet oft zu Original-Seite weiter |

**Workaround bei Download-Problemen:**
1. Video in der App herunterladen (TikTok: "Speichern", Instagram: Drittanbieter-App)
2. Video direkt an den Bot senden
3. Optional: Original-URL als Caption hinzufügen für Kontext

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
- **Gemini 2.0 Flash**: ~$0.00001 pro Rezept (praktisch kostenlos)
- **Hosting**: Dein eigener Server/NAS/Raspberry Pi

## Troubleshooting

### "Download fehlgeschlagen"

TikTok und Instagram blockieren oft Downloads. Lösung:
1. Video auf dem Handy herunterladen (mit TikTok-App oder Drittanbieter-App)
2. Video direkt an den Bot senden

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
├── config.py           # Konfiguration
├── config.yaml.example # Englische Config-Vorlage
├── config.yaml.de_example # Deutsche Config-Vorlage
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── README.md           # Englisch
└── README.de.md        # Deutsch
```

## Lizenz

MIT

## Ähnliche Projekte

- [Tandoor Recipes](https://github.com/TandoorRecipes/recipes) - Self-hosted Recipe Manager
- [Mealie](https://github.com/mealie-recipes/mealie) - Self-hosted Recipe Manager
- [Cooklang](https://cooklang.org/) - Markup-Sprache für Rezepte
