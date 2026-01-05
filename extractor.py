"""Extrahiert Rezepte aus Medien mittels Gemini AI."""

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from google import genai

from config import Config

logger = logging.getLogger(__name__)


# =============================================================================
# DATENMODELL
# =============================================================================

@dataclass
class VideoMetadata:
    """Metadaten eines Videos von yt-dlp."""
    title: str | None = None
    description: str | None = None
    uploader: str | None = None
    duration: int | None = None  # Sekunden
    tags: list[str] = field(default_factory=list)
    subtitles: str | None = None  # Extrahierter Untertitel-Text
    platform: str | None = None  # youtube, tiktok, instagram


@dataclass
class Recipe:
    """Vollständiges Rezept mit allen extrahierten Informationen."""
    title: str
    servings: str | None = None
    prep_time: str | None = None
    cook_time: str | None = None
    total_time: str | None = None
    difficulty: str | None = None  # einfach, mittel, schwer
    tags: list[str] = field(default_factory=list)
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # Tipps, Variationen
    source_url: str | None = None
    source_platform: str | None = None  # tiktok, youtube, instagram, web
    creator: str | None = None


IMAGE_PROMPT = """Erstelle ein appetitliches Food-Foto von diesem Gericht: {title}

Anforderungen:
- Professionelles Food-Fotografie-Styling
- Das fertige Gericht auf einem schönen Teller/in einer Schüssel
- Natürliches, warmes Licht
- Leicht von oben fotografiert (45° Winkel)
- Keine Personen, kein Text, keine Logos
- Sauberer, einfacher Hintergrund (Holztisch oder neutral)
"""


def generate_recipe_image(config, recipe_title: str) -> bytes | None:
    """Generiert ein Vorschaubild für das Rezept."""
    try:
        client = genai.Client(api_key=config.gemini.api_key)

        prompt = IMAGE_PROMPT.format(title=recipe_title)

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[prompt],
            config={"response_modalities": ["IMAGE", "TEXT"]},
        )

        # Bild aus Response extrahieren
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                logger.info(f"Bild generiert für: {recipe_title}")
                return part.inline_data.data

        logger.warning("Kein Bild in Response gefunden")
        return None

    except Exception as e:
        logger.warning(f"Bildgenerierung fehlgeschlagen: {e}")
        return None


def fetch_webpage_text(url: str) -> str | None:
    """Ruft Webseiten-Inhalt ab und extrahiert den Text."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Entferne Script/Style
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Extrahiere Text
        text = soup.get_text(separator="\n", strip=True)

        # Bereinige Leerzeilen
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        # Limitiere auf ~4000 Zeichen
        if len(text) > 4000:
            text = text[:4000] + "..."

        logger.info(f"Webseite abgerufen: {len(text)} Zeichen")
        return text

    except Exception as e:
        logger.warning(f"Konnte Webseite nicht abrufen: {e}")
        return None

EXTRACTION_PROMPT = """WICHTIG: Antworte KOMPLETT auf Deutsch! Alle Texte müssen auf Deutsch sein.

Analysiere ALLE bereitgestellten Quellen und extrahiere das Rezept vollständig.

QUELLEN-PRIORISIERUNG (bei Konflikten):
1. Untertitel/Captions (genaueste Quelle für gesprochene Mengenangaben)
2. Video-Beschreibung (oft vollständige Zutatenlisten)
3. Video-Inhalt (visuelle Informationen)
4. Webseiten-Text (Kontext)

Antworte NUR mit einem JSON-Objekt in diesem Format:
{
  "title": "Name des Gerichts auf Deutsch",
  "servings": "4 Portionen",
  "prep_time": "15 min",
  "cook_time": "30 min",
  "total_time": "45 min",
  "difficulty": "mittel",
  "tags": ["italienisch", "pasta", "vegetarisch"],
  "ingredients": [
    "## Für die Sauce",
    "200g Guanciale",
    "4 Eigelb",
    "## Für die Pasta",
    "400g Spaghetti",
    "Salz"
  ],
  "instructions": [
    "Pasta in reichlich Salzwasser al dente kochen (ca. 8-10 min)",
    "Guanciale in Würfel schneiden und bei mittlerer Hitze knusprig braten",
    "Eigelb mit geriebenem Pecorino vermengen"
  ],
  "equipment": ["großer Topf", "Pfanne", "Reibe"],
  "notes": ["Pancetta als Ersatz für Guanciale möglich", "Pastawasser aufheben zum Binden"]
}

WICHTIG - VOLLSTÄNDIGKEIT:
- Extrahiere ALLE genannten Zutaten mit EXAKTEN Mengenangaben
- Wenn Mengen genannt werden (gesprochen, geschrieben, eingeblendet), übernimm sie GENAU
- Gruppenüberschriften bei Zutaten mit "## " markieren (z.B. "## Für den Teig")
- Jeden Zubereitungsschritt einzeln und detailliert auflisten
- Equipment nur auflisten wenn spezielle Geräte benötigt werden
- Notes für Tipps, Variationen, Ersatzzutaten

UMRECHNUNGEN:
- Mengenangaben in metrischen Einheiten, Original in Klammern: "240ml (1 cup) Milch"
- Temperaturen in Celsius mit Original: "180°C (350°F)"
- "Pinch", "dash" etc. als "1 Prise" übersetzen

SCHWIERIGKEITSGRAD:
- "einfach": Wenige Zutaten, simple Techniken, unter 30 min
- "mittel": Mehrere Schritte, etwas Erfahrung hilfreich
- "schwer": Komplexe Techniken, viele Komponenten, zeitaufwändig

ZEITEN:
- prep_time: Aktive Vorbereitungszeit (Schneiden, Mischen)
- cook_time: Zeit am Herd/Ofen
- total_time: Gesamtzeit inkl. Ruhezeiten
- Falls nur Gesamtzeit bekannt: nur total_time angeben

REGELN:
- ALLE Texte auf Deutsch
- Fehlende Felder weglassen (nicht null oder leer)
- NUR das JSON, kein anderer Text!"""


def extract_recipe_from_video(
    config: Config,
    video_path: Path,
    source_url: str | None = None,
    metadata: VideoMetadata | None = None,
) -> Recipe:
    """
    Extrahiert ein Rezept direkt aus einem Video mittels Gemini.
    Nutzt alle verfügbaren Metadaten für maximale Genauigkeit.
    """
    import time as time_module

    client = genai.Client(api_key=config.gemini.api_key)

    logger.info(f"Lade Video hoch: {video_path}")
    video_file = client.files.upload(file=str(video_path))

    logger.info("Warte auf Verarbeitung...")
    while video_file.state.name == "PROCESSING":
        time_module.sleep(2)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError("Video-Upload fehlgeschlagen")

    # Strukturierten Prompt mit allen verfügbaren Quellen bauen
    prompt = EXTRACTION_PROMPT
    prompt += "\n\n" + "=" * 60
    prompt += "\nVERFÜGBARE QUELLEN:"
    prompt += "\n" + "=" * 60

    if metadata:
        if metadata.subtitles:
            prompt += f"\n\n### 1. UNTERTITEL/CAPTIONS (höchste Priorität für Mengenangaben!):\n{metadata.subtitles}"

        if metadata.description:
            prompt += f"\n\n### 2. VIDEO-BESCHREIBUNG:\n{metadata.description}"

        if metadata.title:
            prompt += f"\n\n### 3. VIDEO-TITEL: {metadata.title}"

        if metadata.uploader:
            prompt += f"\n### 4. CREATOR: {metadata.uploader}"

        if metadata.tags:
            prompt += f"\n### 5. TAGS: {', '.join(metadata.tags[:10])}"

    if source_url:
        prompt += f"\n\n### QUELL-URL: {source_url}"

    prompt += "\n\n" + "=" * 60
    prompt += "\nAnalysiere nun das Video zusammen mit den obigen Quellen."

    logger.info("Sende an Gemini zur Analyse...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[video_file, prompt],
    )

    # Aufräumen
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    recipe = _parse_response(response.text, source_url)

    # Metadaten zum Rezept hinzufügen
    if metadata:
        recipe.source_platform = metadata.platform
        recipe.creator = metadata.uploader

    return recipe


def is_video_platform_url(url: str) -> bool:
    """Prüft ob URL von einer Video-Plattform stammt."""
    video_domains = [
        "tiktok.com",
        "vm.tiktok.com",
        "instagram.com",
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "fb.watch",
    ]
    return any(domain in url.lower() for domain in video_domains)


def detect_platform(url: str) -> str | None:
    """Erkennt die Video-Plattform aus der URL."""
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "facebook"
    return None


def extract_video_metadata(url: str, temp_dir: Path) -> VideoMetadata:
    """Extrahiert alle verfügbaren Metadaten von einem Video."""
    metadata = VideoMetadata(platform=detect_platform(url))

    try:
        # Metadaten als JSON extrahieren
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-download",
                "--dump-json",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            metadata.title = data.get("title")
            metadata.description = data.get("description")
            metadata.uploader = data.get("uploader") or data.get("channel")
            metadata.duration = data.get("duration")
            metadata.tags = data.get("tags", []) or []

            logger.info(f"Metadaten extrahiert: {metadata.title}")

    except subprocess.TimeoutExpired:
        logger.warning("Metadaten-Extraktion Timeout")
    except json.JSONDecodeError:
        logger.warning("Konnte Metadaten-JSON nicht parsen")
    except Exception as e:
        logger.warning(f"Metadaten-Extraktion fehlgeschlagen: {e}")

    # Untertitel extrahieren (separat, da nicht immer verfügbar)
    try:
        subs_path = temp_dir / "subs"
        result = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-lang", "de,en",
                "--sub-format", "vtt/srt/best",
                "-o", str(subs_path),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        # Suche nach heruntergeladenen Untertitel-Dateien
        for ext in [".vtt", ".srt", ".de.vtt", ".en.vtt", ".de.srt", ".en.srt"]:
            sub_file = temp_dir / f"subs{ext}"
            if sub_file.exists():
                raw_subs = sub_file.read_text(encoding="utf-8", errors="ignore")
                metadata.subtitles = _clean_subtitles(raw_subs)
                if metadata.subtitles:
                    logger.info(f"Untertitel extrahiert: {len(metadata.subtitles)} Zeichen")
                break

    except subprocess.TimeoutExpired:
        logger.warning("Untertitel-Extraktion Timeout")
    except Exception as e:
        logger.warning(f"Untertitel-Extraktion fehlgeschlagen: {e}")

    return metadata


def _clean_subtitles(raw_subs: str) -> str | None:
    """Bereinigt VTT/SRT Untertitel zu lesbarem Text."""
    if not raw_subs:
        return None

    lines = []
    seen = set()

    for line in raw_subs.splitlines():
        # Überspringe Timestamps, WEBVTT Header, leere Zeilen
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d{2}:\d{2}", line):  # Timestamp
            continue
        if re.match(r"^\d+$", line):  # Sequenznummer
            continue
        if "-->" in line:  # Timestamp-Range
            continue

        # Entferne VTT-Formatierung
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]+\}", "", line)

        # Dedupliziere (Untertitel wiederholen sich oft)
        if line and line not in seen:
            seen.add(line)
            lines.append(line)

    text = " ".join(lines)
    return text if len(text) > 20 else None


def download_video_from_url(url: str, output_path: Path, temp_dir: Path) -> tuple[Path | None, VideoMetadata]:
    """Lädt Video von URL mit yt-dlp herunter und extrahiert alle Metadaten."""

    # Erst alle Metadaten extrahieren
    metadata = extract_video_metadata(url, temp_dir)

    try:
        # Video herunterladen
        result = subprocess.run(
            [
                "yt-dlp",
                "-f", "best[ext=mp4]/best",
                "--no-playlist",
                "-o", str(output_path),
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0 and output_path.exists():
            logger.info(f"Video heruntergeladen: {output_path} ({output_path.stat().st_size // 1024}KB)")
            return output_path, metadata

        logger.warning(f"yt-dlp Download-Fehler: {result.stderr}")
        return None, metadata

    except subprocess.TimeoutExpired:
        logger.warning("Video-Download Timeout")
        return None, metadata
    except FileNotFoundError:
        logger.warning("yt-dlp nicht installiert")
        return None, metadata
    except Exception as e:
        logger.warning(f"Video-Download fehlgeschlagen: {e}")
        return None, metadata


def extract_recipe_from_url(
    config: Config,
    url: str,
) -> Recipe:
    """
    Extrahiert ein Rezept aus einer URL.
    Bei Video-Plattformen (TikTok, Instagram, YouTube) wird das Video heruntergeladen.
    """
    import tempfile

    # Bei Video-Plattformen: Video herunterladen und analysieren
    if is_video_platform_url(url):
        logger.info(f"Video-Plattform erkannt, lade Video herunter: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_path = temp_path / "video.mp4"
            downloaded, metadata = download_video_from_url(url, video_path, temp_path)

            if downloaded:
                return extract_recipe_from_video(config, downloaded, url, metadata)
            else:
                logger.warning("Video-Download fehlgeschlagen, versuche Webseiten-Text...")

    # Webseiten-Extraktion: Erst Schema versuchen, dann Text
    return extract_recipe_from_webpage(config, url)


def extract_recipe_schema(html: str) -> Recipe | None:
    """
    Extrahiert Rezept aus JSON-LD Schema (schema.org/Recipe).
    Viele Rezeptseiten haben perfekt strukturierte Daten!
    """
    soup = BeautifulSoup(html, "html.parser")

    # Suche JSON-LD Scripts
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)

            # Kann ein einzelnes Objekt oder eine Liste sein
            if isinstance(data, list):
                for item in data:
                    recipe = _parse_schema_recipe(item)
                    if recipe:
                        return recipe
            else:
                # Kann auch @graph enthalten
                if "@graph" in data:
                    for item in data["@graph"]:
                        recipe = _parse_schema_recipe(item)
                        if recipe:
                            return recipe
                else:
                    recipe = _parse_schema_recipe(data)
                    if recipe:
                        return recipe

        except (json.JSONDecodeError, TypeError):
            continue

    return None


def _parse_schema_recipe(data: dict) -> Recipe | None:
    """Parst ein einzelnes JSON-LD Recipe-Objekt."""
    if not isinstance(data, dict):
        return None

    # Prüfe ob es ein Recipe ist
    schema_type = data.get("@type", "")
    if isinstance(schema_type, list):
        if "Recipe" not in schema_type:
            return None
    elif schema_type != "Recipe":
        return None

    # Extrahiere Felder
    title = data.get("name", "")
    if not title:
        return None

    # Zutaten
    ingredients = []
    raw_ingredients = data.get("recipeIngredient", [])
    if isinstance(raw_ingredients, list):
        ingredients = [str(i).strip() for i in raw_ingredients if i]

    # Anweisungen
    instructions = []
    raw_instructions = data.get("recipeInstructions", [])
    if isinstance(raw_instructions, list):
        for item in raw_instructions:
            if isinstance(item, str):
                instructions.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    instructions.append(text.strip())
    elif isinstance(raw_instructions, str):
        instructions = [s.strip() for s in raw_instructions.split("\n") if s.strip()]

    # Zeiten parsen (ISO 8601 Duration: PT30M, PT1H30M, etc.)
    def parse_duration(iso_str: str | None) -> str | None:
        if not iso_str:
            return None
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso_str)
        if match:
            hours = int(match.group(1) or 0)
            mins = int(match.group(2) or 0)
            if hours and mins:
                return f"{hours}h {mins}min"
            elif hours:
                return f"{hours}h"
            elif mins:
                return f"{mins} min"
        return None

    prep_time = parse_duration(data.get("prepTime"))
    cook_time = parse_duration(data.get("cookTime"))
    total_time = parse_duration(data.get("totalTime"))

    # Portionen
    servings = None
    yield_val = data.get("recipeYield")
    if yield_val:
        if isinstance(yield_val, list):
            servings = str(yield_val[0])
        else:
            servings = str(yield_val)

    # Tags/Kategorie
    tags = []
    if data.get("recipeCategory"):
        cat = data["recipeCategory"]
        if isinstance(cat, list):
            tags.extend(cat)
        else:
            tags.append(cat)
    if data.get("recipeCuisine"):
        cuisine = data["recipeCuisine"]
        if isinstance(cuisine, list):
            tags.extend(cuisine)
        else:
            tags.append(cuisine)
    if data.get("keywords"):
        kw = data["keywords"]
        if isinstance(kw, str):
            tags.extend([k.strip() for k in kw.split(",") if k.strip()])

    # Creator/Author
    creator = None
    author = data.get("author")
    if author:
        if isinstance(author, dict):
            creator = author.get("name")
        elif isinstance(author, str):
            creator = author

    logger.info(f"Schema-Rezept gefunden: {title}")

    return Recipe(
        title=title,
        servings=servings,
        prep_time=prep_time,
        cook_time=cook_time,
        total_time=total_time,
        tags=tags[:10],  # Limitiere Tags
        ingredients=ingredients,
        instructions=instructions,
        creator=creator,
        source_platform="web",
    )


def extract_recipe_from_webpage(config: Config, url: str) -> Recipe:
    """
    Extrahiert ein Rezept aus einer Webseite.
    Versucht zuerst JSON-LD Schema, dann Fallback auf Gemini.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        raise ValueError(f"Konnte Webseite nicht abrufen: {e}")

    # Erst Schema versuchen (viel genauer!)
    recipe = extract_recipe_schema(html)
    if recipe:
        recipe.source_url = url
        logger.info("Rezept aus Schema extrahiert (hohe Genauigkeit)")
        return recipe

    # Fallback: Text extrahieren und an Gemini schicken
    logger.info("Kein Schema gefunden, verwende Gemini...")

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if len(text) > 6000:
        text = text[:6000] + "..."

    if len(text) < 100:
        raise ValueError("Konnte keinen ausreichenden Inhalt von der Webseite abrufen")

    client = genai.Client(api_key=config.gemini.api_key)

    prompt = EXTRACTION_PROMPT
    prompt += f"\n\nQuell-URL: {url}"
    prompt += f"\n\n--- Webseiten-Inhalt ---\n{text}"

    logger.info("Sende Webseiten-Text an Gemini...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[prompt],
    )

    recipe = _parse_response(response.text, url)
    recipe.source_platform = "web"
    return recipe


def extract_recipe_from_image(
    config: Config,
    image_path: Path,
    source_url: str | None = None,
) -> Recipe:
    """
    Extrahiert ein Rezept aus einem Bild mittels Gemini.
    """
    client = genai.Client(api_key=config.gemini.api_key)

    # Bild laden
    import PIL.Image
    image = PIL.Image.open(image_path)

    prompt = EXTRACTION_PROMPT

    # Webseiten-Inhalt abrufen falls URL vorhanden
    if source_url:
        prompt += f"\n\nQuell-URL: {source_url}"
        webpage_text = fetch_webpage_text(source_url)
        if webpage_text:
            prompt += f"\n\n--- Webseiten-Inhalt ---\n{webpage_text}"

    logger.info("Sende Bild an Gemini...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[image, prompt],
    )

    return _parse_response(response.text, source_url)


def _parse_response(response_text: str, source_url: str | None) -> Recipe:
    """Parst die Gemini-Antwort zu einem Recipe-Objekt."""
    response_text = response_text.strip()

    # Extrahiere JSON aus Response (entferne evtl. Markdown-Codeblocks)
    if "```" in response_text:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
        if match:
            response_text = match.group(1)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Konnte JSON nicht parsen: {response_text[:500]}")
        raise ValueError(f"Gemini hat kein valides JSON zurückgegeben: {e}")

    # Validiere und erstelle Recipe
    recipe = Recipe(
        title=data.get("title", "Unbekanntes Rezept"),
        servings=data.get("servings"),
        prep_time=data.get("prep_time"),
        cook_time=data.get("cook_time"),
        total_time=data.get("total_time") or data.get("time"),  # Fallback für altes Format
        difficulty=data.get("difficulty"),
        tags=data.get("tags", []),
        ingredients=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        equipment=data.get("equipment", []),
        notes=data.get("notes", []),
        source_url=source_url,
    )

    # Validierung
    _validate_recipe(recipe)

    return recipe


def _validate_recipe(recipe: Recipe) -> None:
    """Validiert ein Rezept und loggt Warnungen bei Problemen."""
    warnings = []

    if not recipe.title or recipe.title == "Unbekanntes Rezept":
        warnings.append("Kein Titel gefunden")

    if not recipe.ingredients:
        warnings.append("Keine Zutaten gefunden")

    if not recipe.instructions:
        warnings.append("Keine Zubereitungsschritte gefunden")

    # Prüfe auf offensichtlich fehlende Mengenangaben
    ingredients_without_amounts = 0
    for ing in recipe.ingredients:
        if not ing.startswith("## "):  # Ignoriere Gruppenüberschriften
            # Hat keine Zahl am Anfang
            if not re.match(r"^\d", ing.strip()):
                ingredients_without_amounts += 1

    if ingredients_without_amounts > len(recipe.ingredients) * 0.7:
        warnings.append(f"{ingredients_without_amounts} Zutaten ohne Mengenangabe")

    if warnings:
        logger.warning(f"Rezept-Validierung: {', '.join(warnings)}")


def format_recipe_chat(recipe: Recipe) -> str:
    """Formatiert ein Rezept für Telegram Chat."""
    lines = [f"🍽 *{recipe.title}*", ""]

    # Meta-Zeile mit allen verfügbaren Infos
    meta = []
    time_str = recipe.total_time or recipe.cook_time
    if time_str:
        meta.append(f"⏱ {time_str}")
    if recipe.servings:
        meta.append(f"👥 {recipe.servings}")
    if recipe.difficulty:
        difficulty_emoji = {"einfach": "🟢", "mittel": "🟡", "schwer": "🔴"}.get(recipe.difficulty.lower(), "")
        meta.append(f"{difficulty_emoji} {recipe.difficulty}")
    if meta:
        lines.append(" | ".join(meta))

    if recipe.tags:
        tags_str = " ".join(f"#{tag.replace(' ', '_')}" for tag in recipe.tags[:8])
        lines.append(f"🏷 {tags_str}")

    lines.append("")
    lines.append("📋 *Zutaten:*")
    for ingredient in recipe.ingredients:
        if ingredient.startswith("## "):
            lines.append(f"\n*{ingredient[3:]}*")
        else:
            lines.append(f"• {ingredient}")

    lines.append("")
    lines.append("👨‍🍳 *Zubereitung:*")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")

    if recipe.equipment:
        lines.append("")
        lines.append(f"🍳 *Equipment:* {', '.join(recipe.equipment)}")

    if recipe.notes:
        lines.append("")
        lines.append("💡 *Tipps:*")
        for note in recipe.notes:
            lines.append(f"• {note}")

    if recipe.source_url:
        lines.append("")
        source_info = f"[Quelle]({recipe.source_url})"
        if recipe.creator:
            source_info = f"[{recipe.creator}]({recipe.source_url})"
        lines.append(f"🔗 {source_info}")

    return "\n".join(lines)


def format_recipe_markdown(recipe: Recipe) -> str:
    """Formatiert ein Rezept als Markdown für Obsidian."""
    lines = []

    # Meta-Block
    meta_parts = []
    if recipe.source_url:
        source_text = recipe.creator or recipe.source_url.split("/")[2]
        meta_parts.append(f"**Quelle:** [{source_text}]({recipe.source_url})")
    if recipe.servings:
        meta_parts.append(f"**Portionen:** {recipe.servings}")

    # Zeiten
    times = []
    if recipe.prep_time:
        times.append(f"Vorbereitung: {recipe.prep_time}")
    if recipe.cook_time:
        times.append(f"Kochen: {recipe.cook_time}")
    if recipe.total_time:
        times.append(f"Gesamt: {recipe.total_time}")
    elif not times and (recipe.prep_time or recipe.cook_time):
        pass  # Keine Gesamtzeit nötig wenn einzelne Zeiten vorhanden
    if times:
        meta_parts.append(f"**Zeit:** {' | '.join(times)}")

    if recipe.difficulty:
        meta_parts.append(f"**Schwierigkeit:** {recipe.difficulty}")

    if recipe.tags:
        tags_str = " ".join(f"#{tag.replace(' ', '-')}" for tag in recipe.tags)
        meta_parts.append(f"**Tags:** {tags_str}")

    lines.extend(meta_parts)
    lines.append("")

    # Zutaten
    lines.append("## Zutaten")
    lines.append("")
    for ingredient in recipe.ingredients:
        if ingredient.startswith("## "):
            lines.append(f"\n### {ingredient[3:]}")
            lines.append("")
        else:
            lines.append(f"- {ingredient}")
    lines.append("")

    # Zubereitung
    lines.append("## Zubereitung")
    lines.append("")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    # Equipment (falls vorhanden)
    if recipe.equipment:
        lines.append("## Equipment")
        lines.append("")
        for item in recipe.equipment:
            lines.append(f"- {item}")
        lines.append("")

    # Tipps/Notizen (falls vorhanden)
    if recipe.notes:
        lines.append("## Tipps")
        lines.append("")
        for note in recipe.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
