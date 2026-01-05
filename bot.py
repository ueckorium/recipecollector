#!/usr/bin/env python3
"""Recipe Collector Telegram Bot."""

import io
import logging
import re
import sys
import tempfile
from pathlib import Path

import telebot
from telebot import types

from config import Config, load_config
from extractor import (
    Recipe,
    extract_recipe_from_video,
    extract_recipe_from_image,
    extract_recipe_from_url,
    format_recipe_chat,
    format_recipe_markdown,
)

# Logging - DEBUG für ausführliche Ausgabe
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Speicher für Rezepte (für Callback-Buttons)
recipe_cache: dict = {}


def create_bot(config: Config) -> telebot.TeleBot:
    """Erstellt und konfiguriert den Bot."""

    bot = telebot.TeleBot(config.telegram.bot_token)
    telebot.logger.setLevel(logging.DEBUG)

    def is_user_allowed(user_id: int) -> bool:
        if not config.telegram.allowed_users:
            return True
        return user_id in config.telegram.allowed_users

    def sanitize_filename(text: str) -> str:
        """Macht Text filesystem-safe aber human-readable."""
        # Entferne ungültige Zeichen für Dateinamen
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        # Mehrfache Leerzeichen zu einem
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:80]

    def create_recipe_buttons(recipe_id: str) -> types.InlineKeyboardMarkup:
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

    def send_recipe(message: types.Message, recipe: Recipe):
        """Sendet ein formatiertes Rezept."""
        recipe_id = f"{message.chat.id}_{message.message_id}"
        recipe_cache[recipe_id] = recipe

        text = format_recipe_chat(recipe)
        markup = create_recipe_buttons(recipe_id)

        bot.send_message(
            message.chat.id,
            text,
            parse_mode="Markdown",
            reply_markup=markup,
            disable_web_page_preview=True,
        )

        # Automatisch speichern falls konfiguriert
        if config.storage.enabled and config.storage.path:
            try:
                config.storage.path.mkdir(parents=True, exist_ok=True)

                base_name = sanitize_filename(recipe.title)
                md_filename = f"{base_name}.md"
                md_path = config.storage.path / md_filename

                counter = 1
                while md_path.exists():
                    base_name = f"{sanitize_filename(recipe.title)}-{counter}"
                    md_filename = f"{base_name}.md"
                    md_path = config.storage.path / md_filename
                    counter += 1

                markdown = format_recipe_markdown(recipe)
                md_path.write_text(markdown, encoding="utf-8")
                logger.info(f"Rezept automatisch gespeichert: {md_path}")

            except Exception as e:
                logger.exception("Fehler beim automatischen Speichern")

    # === Handler ===

    @bot.message_handler(commands=["start", "help"])
    def handle_start(message: types.Message):
        logger.debug(f"Start/Help von User {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            bot.reply_to(message, "⛔ Du bist nicht berechtigt, diesen Bot zu nutzen.")
            return

        help_text = """🍽 *Recipe Collector Bot*

Sende mir ein Rezept-Video oder einen Link, und ich extrahiere das Rezept für dich!

*Unterstützt:*
• 📹 Videos (direkt senden)
• 📷 Bilder/Screenshots

*Befehle:*
/start - Diese Hilfe anzeigen
/id - Deine User-ID anzeigen
"""
        bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

    @bot.message_handler(commands=["id"])
    def handle_id(message: types.Message):
        logger.debug(f"ID-Anfrage von User {message.from_user.id}")
        bot.reply_to(message, f"Deine User-ID: `{message.from_user.id}`", parse_mode="Markdown")

    @bot.message_handler(func=lambda m: m.text and re.search(r'https?://[^\s]+', m.text))
    def handle_url(message: types.Message):
        logger.info(f"URL empfangen von User {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            return

        url_match = re.search(r'https?://[^\s]+', message.text)
        if not url_match:
            return

        url = url_match.group(0)
        status = bot.reply_to(message, "⏳ Lade Webseite...")

        try:
            bot.edit_message_text("⏳ Analysiere Rezept...", message.chat.id, status.message_id)
            recipe = extract_recipe_from_url(config, url)

            logger.info(f"Rezept extrahiert: {recipe.title}")
            bot.delete_message(message.chat.id, status.message_id)
            send_recipe(message, recipe)

        except Exception as e:
            logger.exception("Fehler bei URL-Verarbeitung")
            bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["video", "video_note", "animation"])
    def handle_video(message: types.Message):
        logger.info(f"Video empfangen von User {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            logger.warning(f"User {message.from_user.id} nicht erlaubt")
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

                logger.debug(f"Lade Video herunter: {file_info.file_path}")
                downloaded = bot.download_file(file_info.file_path)
                video_path = temp_path / "video.mp4"
                video_path.write_bytes(downloaded)
                logger.debug(f"Video gespeichert: {video_path} ({video_path.stat().st_size} bytes)")

                # URL aus Caption
                source_url = None
                if message.caption:
                    import re
                    url_match = re.search(r'https?://[^\s]+', message.caption)
                    if url_match:
                        source_url = url_match.group(0)

                # Direkt an Gemini schicken
                bot.edit_message_text("⏳ Analysiere Video...", message.chat.id, status.message_id)
                recipe = extract_recipe_from_video(config, video_path, source_url)

                logger.info(f"Rezept extrahiert: {recipe.title}")
                bot.delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception as e:
            logger.exception("Fehler bei Video-Verarbeitung")
            bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["photo"])
    def handle_photo(message: types.Message):
        logger.info(f"Foto empfangen von User {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            return

        status = bot.reply_to(message, "⏳ Verarbeite Bild...")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                photo = message.photo[-1]
                file_info = bot.get_file(photo.file_id)
                logger.debug(f"Lade Bild herunter: {file_info.file_path}")
                downloaded = bot.download_file(file_info.file_path)

                image_path = temp_path / "image.jpg"
                image_path.write_bytes(downloaded)

                # URL aus Caption
                source_url = None
                if message.caption:
                    import re
                    url_match = re.search(r'https?://[^\s]+', message.caption)
                    if url_match:
                        source_url = url_match.group(0)

                bot.edit_message_text("⏳ Analysiere Bild...", message.chat.id, status.message_id)
                recipe = extract_recipe_from_image(config, image_path, source_url)

                logger.info(f"Rezept extrahiert: {recipe.title}")
                bot.delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception as e:
            logger.exception("Fehler bei Bild-Verarbeitung")
            bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["document"])
    def handle_document(message: types.Message):
        logger.info(f"Dokument empfangen von User {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            return

        doc = message.document
        if not doc.mime_type:
            return

        is_video = doc.mime_type.startswith("video/")
        is_image = doc.mime_type.startswith("image/")

        if not (is_video or is_image):
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

                # URL aus Caption
                source_url = None
                if message.caption:
                    import re
                    url_match = re.search(r'https?://[^\s]+', message.caption)
                    if url_match:
                        source_url = url_match.group(0)

                bot.edit_message_text("⏳ Analysiere...", message.chat.id, status.message_id)

                if is_video:
                    recipe = extract_recipe_from_video(config, file_path, source_url)
                else:
                    recipe = extract_recipe_from_image(config, file_path, source_url)

                logger.info(f"Rezept extrahiert: {recipe.title}")
                bot.delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception as e:
            logger.exception("Fehler bei Dokument-Verarbeitung")
            bot.edit_message_text(f"❌ Fehler: {e}", message.chat.id, status.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("md:"))
    def handle_markdown_callback(call: types.CallbackQuery):
        logger.debug(f"Markdown-Button geklickt: {call.data}")
        recipe_id = call.data[3:]
        recipe = recipe_cache.get(recipe_id)

        if not recipe:
            bot.answer_callback_query(call.id, "❌ Rezept nicht mehr verfügbar")
            return

        base_name = sanitize_filename(recipe.title)
        markdown = format_recipe_markdown(recipe)
        md_file = io.BytesIO(markdown.encode("utf-8"))
        md_file.name = f"{base_name}.md"

        bot.send_document(call.message.chat.id, md_file, caption=f"📄 {recipe.title}")
        bot.answer_callback_query(call.id, "✅ Markdown gesendet")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("save:"))
    def handle_save_callback(call: types.CallbackQuery):
        logger.debug(f"Speichern-Button geklickt: {call.data}")
        if not config.storage.enabled or not config.storage.path:
            bot.answer_callback_query(call.id, "❌ Speichern nicht konfiguriert")
            return

        recipe_id = call.data[5:]
        recipe = recipe_cache.get(recipe_id)

        if not recipe:
            bot.answer_callback_query(call.id, "❌ Rezept nicht mehr verfügbar")
            return

        try:
            config.storage.path.mkdir(parents=True, exist_ok=True)

            base_name = sanitize_filename(recipe.title)
            md_filename = f"{base_name}.md"
            md_path = config.storage.path / md_filename

            counter = 1
            while md_path.exists():
                base_name = f"{sanitize_filename(recipe.title)}-{counter}"
                md_filename = f"{base_name}.md"
                md_path = config.storage.path / md_filename
                counter += 1

            markdown = format_recipe_markdown(recipe)
            md_path.write_text(markdown, encoding="utf-8")

            bot.answer_callback_query(call.id, f"✅ Gespeichert: {md_filename}")
            logger.info(f"Rezept gespeichert: {md_path}")

        except Exception as e:
            logger.exception("Fehler beim Speichern")
            bot.answer_callback_query(call.id, f"❌ Fehler: {e}")

    return bot


def main():
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

    logger.info("Konfiguration geladen")

    if config.telegram.allowed_users:
        logger.info(f"Erlaubte User: {config.telegram.allowed_users}")
    else:
        logger.warning("WARNUNG: Keine User-Whitelist - jeder kann den Bot nutzen!")

    if config.storage.enabled:
        logger.info(f"Speicherort: {config.storage.path}")

    bot = create_bot(config)

    logger.info("Bot gestartet! Warte auf Nachrichten...")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
