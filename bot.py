#!/usr/bin/env python3
"""Recipe Collector Telegram Bot."""

import io
import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path

import telebot
from telebot import types

from config import Config, load_config
from extractor import Recipe, extract_recipe, format_recipe_chat, format_recipe_markdown
from media_handler import (
    download_video,
    extract_url,
    get_video_frames,
    is_image_file,
    is_url,
    is_video_file,
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Globale Config und Bot
config: Config
bot: telebot.TeleBot

# Speicher für Rezepte (für Callback-Buttons)
recipe_cache: dict[str, Recipe] = {}


def is_user_allowed(user_id: int) -> bool:
    """Prüft ob ein User den Bot nutzen darf."""
    if not config.telegram.allowed_users:
        return True  # Leere Liste = alle erlaubt
    return user_id in config.telegram.allowed_users


def slugify(text: str) -> str:
    """Konvertiert Text zu einem sicheren Dateinamen."""
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    for old, new in replacements.items():
        text = text.replace(old, new).replace(old.upper(), new.capitalize())
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:50]


def create_recipe_buttons(recipe_id: str) -> types.InlineKeyboardMarkup:
    """Erstellt Inline-Buttons für ein Rezept."""
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn_markdown = types.InlineKeyboardButton(
        "📄 Als Markdown",
        callback_data=f"md:{recipe_id}"
    )

    buttons = [btn_markdown]

    if config.storage.enabled:
        btn_save = types.InlineKeyboardButton(
            "💾 Speichern",
            callback_data=f"save:{recipe_id}"
        )
        buttons.append(btn_save)

    markup.add(*buttons)
    return markup


def process_media(message: types.Message, media_paths: list[Path], source_url: str | None = None):
    """Verarbeitet Medien und sendet das Rezept."""
    try:
        # Extrahiere Rezept
        recipe = extract_recipe(config, media_paths, source_url)

        # Speichere im Cache für Buttons
        recipe_id = f"{message.chat.id}_{message.message_id}"
        recipe_cache[recipe_id] = recipe

        # Formatiere und sende
        text = format_recipe_chat(recipe)
        markup = create_recipe_buttons(recipe_id)

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=markup,
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.exception("Fehler bei Rezept-Extraktion")
        bot.reply_to(message, f"❌ Fehler: {e}")


@bot.message_handler(commands=["start", "help"])
def handle_start(message: types.Message):
    """Begrüßungsnachricht."""
    if not is_user_allowed(message.from_user.id):
        bot.reply_to(message, "⛔ Du bist nicht berechtigt, diesen Bot zu nutzen.")
        return

    help_text = """🍽 *Recipe Collector Bot*

Sende mir ein Rezept-Video oder einen Link, und ich extrahiere das Rezept für dich!

*Unterstützt:*
• 📹 Videos (direkt senden)
• 🔗 Links (TikTok, Instagram, YouTube)
• 📷 Bilder/Screenshots

*Befehle:*
/start - Diese Hilfe anzeigen
/id - Deine User-ID anzeigen
"""
    bot.send_message(message.chat.id, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["id"])
def handle_id(message: types.Message):
    """Zeigt die User-ID an (für Config)."""
    bot.reply_to(message, f"Deine User-ID: `{message.from_user.id}`", parse_mode="Markdown")


@bot.message_handler(content_types=["video", "video_note", "animation"])
def handle_video(message: types.Message):
    """Verarbeitet gesendete Videos."""
    if not is_user_allowed(message.from_user.id):
        return

    status = bot.reply_to(message, "⏳ Verarbeite Video...")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Video herunterladen
            if message.video:
                file_info = bot.get_file(message.video.file_id)
            elif message.video_note:
                file_info = bot.get_file(message.video_note.file_id)
            else:
                file_info = bot.get_file(message.animation.file_id)

            downloaded = bot.download_file(file_info.file_path)
            video_path = temp_path / "video.mp4"
            video_path.write_bytes(downloaded)

            # Frames extrahieren
            bot.edit_message_text("⏳ Extrahiere Frames...", message.chat.id, status.message_id)
            frames = get_video_frames(video_path, num_frames=5)

            if not frames:
                bot.edit_message_text("❌ Konnte keine Frames extrahieren", message.chat.id, status.message_id)
                return

            # URL aus Caption extrahieren falls vorhanden
            source_url = extract_url(message.caption) if message.caption else None

            # Rezept extrahieren
            bot.edit_message_text("⏳ Analysiere Rezept...", message.chat.id, status.message_id)
            bot.delete_message(message.chat.id, status.message_id)
            process_media(message, frames, source_url)

    except Exception as e:
        logger.exception("Fehler bei Video-Verarbeitung")
        bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)


@bot.message_handler(content_types=["photo"])
def handle_photo(message: types.Message):
    """Verarbeitet gesendete Bilder."""
    if not is_user_allowed(message.from_user.id):
        return

    status = bot.reply_to(message, "⏳ Verarbeite Bild...")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Größtes Bild nehmen
            photo = message.photo[-1]
            file_info = bot.get_file(photo.file_id)
            downloaded = bot.download_file(file_info.file_path)

            image_path = temp_path / "image.jpg"
            image_path.write_bytes(downloaded)

            # URL aus Caption extrahieren
            source_url = extract_url(message.caption) if message.caption else None

            bot.edit_message_text("⏳ Analysiere Rezept...", message.chat.id, status.message_id)
            bot.delete_message(message.chat.id, status.message_id)
            process_media(message, [image_path], source_url)

    except Exception as e:
        logger.exception("Fehler bei Bild-Verarbeitung")
        bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)


@bot.message_handler(content_types=["document"])
def handle_document(message: types.Message):
    """Verarbeitet gesendete Dokumente (Videos/Bilder als Datei)."""
    if not is_user_allowed(message.from_user.id):
        return

    doc = message.document
    if not doc.mime_type:
        return

    if not (doc.mime_type.startswith("video/") or doc.mime_type.startswith("image/")):
        bot.reply_to(message, "❌ Bitte sende ein Video oder Bild.")
        return

    status = bot.reply_to(message, "⏳ Verarbeite Datei...")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            file_info = bot.get_file(doc.file_id)
            downloaded = bot.download_file(file_info.file_path)

            file_path = temp_path / doc.file_name
            file_path.write_bytes(downloaded)

            source_url = extract_url(message.caption) if message.caption else None

            if doc.mime_type.startswith("video/"):
                bot.edit_message_text("⏳ Extrahiere Frames...", message.chat.id, status.message_id)
                frames = get_video_frames(file_path, num_frames=5)
                if not frames:
                    bot.edit_message_text("❌ Konnte keine Frames extrahieren", message.chat.id, status.message_id)
                    return
                media_paths = frames
            else:
                media_paths = [file_path]

            bot.edit_message_text("⏳ Analysiere Rezept...", message.chat.id, status.message_id)
            bot.delete_message(message.chat.id, status.message_id)
            process_media(message, media_paths, source_url)

    except Exception as e:
        logger.exception("Fehler bei Dokument-Verarbeitung")
        bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)


@bot.message_handler(func=lambda m: m.text and is_url(m.text.strip()))
def handle_url(message: types.Message):
    """Verarbeitet URLs."""
    if not is_user_allowed(message.from_user.id):
        return

    url = message.text.strip()
    status = bot.reply_to(message, "⏳ Lade Video herunter...")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            video_path = download_video(url, temp_path)

            if not video_path:
                bot.edit_message_text(
                    "❌ Download fehlgeschlagen.\n\n"
                    "Tipp: Lade das Video auf deinem Gerät herunter und sende es direkt.",
                    message.chat.id,
                    status.message_id,
                )
                return

            bot.edit_message_text("⏳ Extrahiere Frames...", message.chat.id, status.message_id)
            frames = get_video_frames(video_path, num_frames=5)

            if not frames:
                bot.edit_message_text("❌ Konnte keine Frames extrahieren", message.chat.id, status.message_id)
                return

            bot.edit_message_text("⏳ Analysiere Rezept...", message.chat.id, status.message_id)
            bot.delete_message(message.chat.id, status.message_id)
            process_media(message, frames, url)

    except Exception as e:
        logger.exception("Fehler bei URL-Verarbeitung")
        bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("md:"))
def handle_markdown_callback(call: types.CallbackQuery):
    """Sendet Rezept als Markdown-Datei."""
    recipe_id = call.data[3:]
    recipe = recipe_cache.get(recipe_id)

    if not recipe:
        bot.answer_callback_query(call.id, "❌ Rezept nicht mehr verfügbar")
        return

    markdown = format_recipe_markdown(recipe)
    filename = f"{slugify(recipe.title)}.md"

    # Sende als Datei
    file_data = io.BytesIO(markdown.encode("utf-8"))
    file_data.name = filename

    bot.send_document(call.message.chat.id, file_data, caption=f"📄 {recipe.title}")
    bot.answer_callback_query(call.id, "✅ Markdown gesendet")


@bot.callback_query_handler(func=lambda call: call.data.startswith("save:"))
def handle_save_callback(call: types.CallbackQuery):
    """Speichert Rezept im Obsidian Vault."""
    if not config.storage.enabled or not config.storage.path:
        bot.answer_callback_query(call.id, "❌ Speichern nicht konfiguriert")
        return

    recipe_id = call.data[5:]
    recipe = recipe_cache.get(recipe_id)

    if not recipe:
        bot.answer_callback_query(call.id, "❌ Rezept nicht mehr verfügbar")
        return

    try:
        # Stelle sicher dass Ordner existiert
        config.storage.path.mkdir(parents=True, exist_ok=True)

        # Dateiname
        filename = f"{slugify(recipe.title)}.md"
        file_path = config.storage.path / filename

        # Bei Duplikat: Nummer hinzufügen
        counter = 1
        while file_path.exists():
            filename = f"{slugify(recipe.title)}-{counter}.md"
            file_path = config.storage.path / filename
            counter += 1

        # Speichern
        markdown = format_recipe_markdown(recipe)
        file_path.write_text(markdown, encoding="utf-8")

        bot.answer_callback_query(call.id, f"✅ Gespeichert: {filename}")
        logger.info(f"Rezept gespeichert: {file_path}")

    except Exception as e:
        logger.exception("Fehler beim Speichern")
        bot.answer_callback_query(call.id, f"❌ Fehler: {e}")


def main():
    global config, bot

    logger.info("Recipe Collector Bot startet...")

    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("config.yaml nicht gefunden! Kopiere config.yaml.example nach config.yaml")
        sys.exit(1)

    if not config.telegram.bot_token:
        logger.error("Kein Bot-Token konfiguriert!")
        sys.exit(1)

    if not config.gemini.api_key:
        logger.error("Kein Gemini API-Key konfiguriert!")
        sys.exit(1)

    bot = telebot.TeleBot(config.telegram.bot_token)

    # Handler registrieren
    bot.register_message_handler(handle_start, commands=["start", "help"])
    bot.register_message_handler(handle_id, commands=["id"])
    bot.register_message_handler(handle_video, content_types=["video", "video_note", "animation"])
    bot.register_message_handler(handle_photo, content_types=["photo"])
    bot.register_message_handler(handle_document, content_types=["document"])
    bot.register_message_handler(handle_url, func=lambda m: m.text and is_url(m.text.strip()))
    bot.register_callback_query_handler(handle_markdown_callback, func=lambda c: c.data.startswith("md:"))
    bot.register_callback_query_handler(handle_save_callback, func=lambda c: c.data.startswith("save:"))

    logger.info("Bot gestartet! Warte auf Nachrichten...")

    if config.telegram.allowed_users:
        logger.info(f"Erlaubte User: {config.telegram.allowed_users}")
    else:
        logger.warning("WARNUNG: Keine User-Whitelist konfiguriert - jeder kann den Bot nutzen!")

    if config.storage.enabled:
        logger.info(f"Speicherort: {config.storage.path}")

    # Polling starten
    bot.infinity_polling()


if __name__ == "__main__":
    main()
