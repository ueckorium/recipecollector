"""Extrahiert Rezepte aus Medien mittels Gemini AI."""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from config import Config

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Analysiere dieses Koch-Video/Bild und extrahiere das Rezept.

Antworte NUR mit einem JSON-Objekt in diesem Format:
{
  "title": "Name des Gerichts",
  "servings": "4 Portionen",
  "time": "30 min",
  "tags": ["italienisch", "pasta", "vegetarisch"],
  "ingredients": [
    "400g Spaghetti",
    "200g Guanciale",
    "4 Eigelb"
  ],
  "instructions": [
    "Pasta in Salzwasser kochen",
    "Guanciale knusprig braten",
    "Alles vermengen"
  ]
}

Regeln:
- Erkenne automatisch passende Tags (Küche, Diät, Schwierigkeit, etc.)
- Mengenangaben so genau wie möglich
- Zubereitungsschritte klar und präzise
- Wenn Informationen fehlen, schätze sinnvoll oder lasse das Feld weg
- Antworte auf Deutsch
- NUR das JSON, kein anderer Text!"""


@dataclass
class Recipe:
    title: str
    servings: str | None
    time: str | None
    tags: list[str]
    ingredients: list[str]
    instructions: list[str]
    source_url: str | None = None


def extract_recipe(
    config: Config,
    media_paths: list[Path],
    source_url: str | None = None,
) -> Recipe:
    """
    Extrahiert ein Rezept aus Bildern/Video-Frames mittels Gemini.

    Args:
        config: App-Konfiguration
        media_paths: Liste von Bild-Pfaden (oder Video-Frames)
        source_url: Original-URL des Rezepts

    Returns:
        Extrahiertes Recipe-Objekt
    """
    genai.configure(api_key=config.gemini.api_key)
    model = genai.GenerativeModel(config.gemini.model)

    # Bereite Medien für Gemini vor
    content = [EXTRACTION_PROMPT]

    for media_path in media_paths:
        if media_path.exists():
            img = Image.open(media_path)
            content.append(img)

    if source_url:
        content.append(f"\nQuell-URL: {source_url}")

    logger.info(f"Sende {len(media_paths)} Bilder an Gemini...")

    response = model.generate_content(content)
    response_text = response.text.strip()

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

    return Recipe(
        title=data.get("title", "Unbekanntes Rezept"),
        servings=data.get("servings"),
        time=data.get("time"),
        tags=data.get("tags", []),
        ingredients=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        source_url=source_url,
    )


def format_recipe_chat(recipe: Recipe) -> str:
    """Formatiert ein Rezept für Telegram Chat."""
    lines = [f"🍽 *{recipe.title}*", ""]

    # Meta-Zeile
    meta = []
    if recipe.time:
        meta.append(f"⏱ {recipe.time}")
    if recipe.servings:
        meta.append(f"👥 {recipe.servings}")
    if meta:
        lines.append(" | ".join(meta))

    # Tags
    if recipe.tags:
        tags_str = " ".join(f"#{tag.replace(' ', '_')}" for tag in recipe.tags)
        lines.append(f"🏷 {tags_str}")

    lines.append("")

    # Zutaten
    lines.append("📋 *Zutaten:*")
    for ingredient in recipe.ingredients:
        lines.append(f"• {ingredient}")

    lines.append("")

    # Zubereitung
    lines.append("👨‍🍳 *Zubereitung:*")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")

    # Quelle
    if recipe.source_url:
        lines.append("")
        # Kürze URL für Anzeige
        display_url = recipe.source_url.split("//")[-1][:40]
        if len(recipe.source_url.split("//")[-1]) > 40:
            display_url += "..."
        lines.append(f"🔗 [Quelle]({recipe.source_url})")

    return "\n".join(lines)


def format_recipe_markdown(recipe: Recipe) -> str:
    """Formatiert ein Rezept als Markdown für Obsidian."""
    lines = [f"# {recipe.title}", ""]

    # Meta
    meta_parts = []
    if recipe.source_url:
        domain = recipe.source_url.split("/")[2] if "/" in recipe.source_url else recipe.source_url
        meta_parts.append(f"**Quelle:** [{domain}]({recipe.source_url})")
    if recipe.servings:
        meta_parts.append(f"**Portionen:** {recipe.servings}")
    if recipe.time:
        meta_parts.append(f"**Zeit:** {recipe.time}")
    if recipe.tags:
        tags_str = " ".join(f"#{tag.replace(' ', '-')}" for tag in recipe.tags)
        meta_parts.append(f"**Tags:** {tags_str}")

    lines.extend(meta_parts)
    lines.append("")

    # Zutaten
    lines.append("## Zutaten")
    lines.append("")
    for ingredient in recipe.ingredients:
        lines.append(f"- {ingredient}")
    lines.append("")

    # Zubereitung
    lines.append("## Zubereitung")
    lines.append("")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    return "\n".join(lines)
