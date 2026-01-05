#!/usr/bin/env python3
"""Recipe Collector Telegram Bot."""

import io
import logging
import os
import re
import sys
import tempfile
import uuid
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

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


class LRUCache(OrderedDict):
    """Simple LRU cache with maximum size."""

    def __init__(self, maxsize: int = 500):
        super().__init__()
        self.maxsize = maxsize

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

# Logging - level configurable via environment variable (default: INFO)
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Storage for recipes (for callback buttons) - LRU cache prevents memory leak
recipe_cache: LRUCache[str, Recipe] = LRUCache(maxsize=500)


# =============================================================================
# HELPER FUNCTIONS (independent of bot instance)
# =============================================================================

def sanitize_filename(text: str) -> str:
    """Makes text filesystem-safe but human-readable."""
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:80]


def is_valid_url(url: str) -> bool:
    """Checks if a URL is valid (HTTP/HTTPS with hostname)."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def extract_url_from_caption(caption: str | None) -> str | None:
    """Extracts and validates a URL from caption text."""
    if not caption:
        return None
    url_match = re.search(r'https?://[^\s]+', caption)
    if url_match:
        url = url_match.group(0).rstrip(".,;:!?)")
        return url if is_valid_url(url) else None
    return None


def save_recipe_to_file(recipe: Recipe, storage_path: Path) -> Path:
    """Saves a recipe as markdown file with unique name."""
    storage_path.mkdir(parents=True, exist_ok=True)

    base_name = sanitize_filename(recipe.title)
    md_filename = f"{base_name}.md"
    md_path = storage_path / md_filename

    if md_path.exists():
        unique_id = str(uuid.uuid4())[:8]
        md_filename = f"{base_name}-{unique_id}.md"
        md_path = storage_path / md_filename

    markdown = format_recipe_markdown(recipe)
    md_path.write_text(markdown, encoding="utf-8")
    return md_path


# =============================================================================
# BOT FACTORY
# =============================================================================

def create_bot(config: Config) -> telebot.TeleBot:
    """Creates and configures the bot."""

    bot = telebot.TeleBot(config.telegram.bot_token)
    telebot.logger.setLevel(getattr(logging, _log_level, logging.INFO))

    def is_user_allowed(user_id: int) -> bool:
        if not config.telegram.allowed_users:
            return True
        return user_id in config.telegram.allowed_users

    def authorized_handler(handler_name: str):
        """Decorator for handlers with user authorization and logging."""
        def decorator(func):
            def wrapper(message: types.Message):
                user_id = message.from_user.id
                logger.info(f"{handler_name} from user {user_id}")
                if not is_user_allowed(user_id):
                    logger.warning(f"User {user_id} not authorized")
                    return
                return func(message)
            return wrapper
        return decorator

    def safe_delete_message(chat_id: int, message_id: int) -> None:
        """Safely deletes a message (ignores errors if already deleted)."""
        try:
            bot.delete_message(chat_id, message_id)
        except telebot.apihelper.ApiTelegramException:
            pass  # Message no longer exists

    def safe_edit_message(text: str, chat_id: int, message_id: int) -> None:
        """Safely edits a message (ignores errors)."""
        try:
            bot.edit_message_text(text, chat_id, message_id)
        except telebot.apihelper.ApiTelegramException:
            pass  # Message no longer exists or text unchanged

    def create_recipe_buttons(recipe_id: str) -> types.InlineKeyboardMarkup:
        markup = types.InlineKeyboardMarkup(row_width=2)
        btn_markdown = types.InlineKeyboardButton(
            "📄 As Markdown",
            callback_data=f"md:{recipe_id}"
        )
        buttons = [btn_markdown]
        if config.storage.enabled:
            btn_save = types.InlineKeyboardButton(
                "💾 Save",
                callback_data=f"save:{recipe_id}"
            )
            buttons.append(btn_save)
        markup.add(*buttons)
        return markup

    def send_recipe(message: types.Message, recipe: Recipe):
        """Sends a formatted recipe."""
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

        # Auto-save if configured
        if config.storage.enabled and config.storage.path:
            try:
                md_path = save_recipe_to_file(recipe, config.storage.path)
                logger.info(f"Recipe auto-saved: {md_path}")
            except Exception as e:
                logger.exception("Error during auto-save")

    # === Handlers ===

    @bot.message_handler(commands=["start", "help"])
    def handle_start(message: types.Message):
        logger.debug(f"Start/Help from user {message.from_user.id}")
        if not is_user_allowed(message.from_user.id):
            bot.reply_to(message, "⛔ You are not authorized to use this bot.")
            return

        help_text = """🍽 *Recipe Collector Bot*

Send me a recipe video or link, and I'll extract the recipe for you!

*Supported:*
• 📹 Videos (send directly)
• 📷 Images/Screenshots

*Commands:*
/start - Show this help
/id - Show your user ID
"""
        bot.send_message(message.chat.id, help_text, parse_mode="Markdown")

    @bot.message_handler(commands=["id"])
    def handle_id(message: types.Message):
        logger.debug(f"ID request from user {message.from_user.id}")
        bot.reply_to(message, f"Your user ID: `{message.from_user.id}`", parse_mode="Markdown")

    @bot.message_handler(func=lambda m: m.text and re.search(r'https?://[^\s]+', m.text))
    @authorized_handler("URL received")
    def handle_url(message: types.Message):
        url_match = re.search(r'https?://[^\s]+', message.text)
        if not url_match:
            return

        url = url_match.group(0).rstrip(".,;:!?)")  # Remove punctuation
        if not is_valid_url(url):
            bot.reply_to(message, "❌ Invalid URL.")
            return

        status = bot.reply_to(message, "⏳ Loading webpage...")

        try:
            safe_edit_message("⏳ Analyzing recipe...", message.chat.id, status.message_id)
            recipe = extract_recipe_from_url(config, url)

            logger.info(f"Recipe extracted: {recipe.title}")
            safe_delete_message(message.chat.id, status.message_id)
            send_recipe(message, recipe)

        except Exception:
            logger.exception("Error processing URL")
            safe_edit_message("❌ Processing failed. Please try again.", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["video", "video_note", "animation"])
    @authorized_handler("Video received")
    def handle_video(message: types.Message):
        status = bot.reply_to(message, "⏳ Processing video...")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Download video
                if message.video:
                    file_info = bot.get_file(message.video.file_id)
                elif message.video_note:
                    file_info = bot.get_file(message.video_note.file_id)
                else:
                    file_info = bot.get_file(message.animation.file_id)

                logger.debug(f"Downloading video: {file_info.file_path}")
                downloaded = bot.download_file(file_info.file_path)
                video_path = temp_path / "video.mp4"
                video_path.write_bytes(downloaded)
                logger.debug(f"Video saved: {video_path} ({video_path.stat().st_size} bytes)")

                # URL from caption
                source_url = extract_url_from_caption(message.caption)

                # Send directly to Gemini
                safe_edit_message("⏳ Analyzing video...", message.chat.id, status.message_id)
                recipe = extract_recipe_from_video(config, video_path, source_url)

                logger.info(f"Recipe extracted: {recipe.title}")
                safe_delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception:
            logger.exception("Error processing video")
            safe_edit_message("❌ Video processing failed. Please try again.", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["photo"])
    @authorized_handler("Photo received")
    def handle_photo(message: types.Message):
        status = bot.reply_to(message, "⏳ Processing image...")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                photo = message.photo[-1]
                file_info = bot.get_file(photo.file_id)
                logger.debug(f"Downloading image: {file_info.file_path}")
                downloaded = bot.download_file(file_info.file_path)

                image_path = temp_path / "image.jpg"
                image_path.write_bytes(downloaded)

                # URL from caption
                source_url = extract_url_from_caption(message.caption)

                safe_edit_message("⏳ Analyzing image...", message.chat.id, status.message_id)
                recipe = extract_recipe_from_image(config, image_path, source_url)

                logger.info(f"Recipe extracted: {recipe.title}")
                safe_delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception:
            logger.exception("Error processing image")
            safe_edit_message("❌ Image processing failed. Please try again.", message.chat.id, status.message_id)

    @bot.message_handler(content_types=["document"])
    @authorized_handler("Document received")
    def handle_document(message: types.Message):
        doc = message.document
        if not doc.mime_type:
            return

        is_video = doc.mime_type.startswith("video/")
        is_image = doc.mime_type.startswith("image/")

        if not (is_video or is_image):
            bot.reply_to(message, "❌ Please send a video or image.")
            return

        status = bot.reply_to(message, "⏳ Processing file...")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                file_info = bot.get_file(doc.file_id)
                downloaded = bot.download_file(file_info.file_path)

                # Path traversal protection: basename + sanitize for complete protection
                raw_name = os.path.basename(doc.file_name) if doc.file_name else "document"
                safe_filename = sanitize_filename(raw_name) or "document"
                file_path = temp_path / safe_filename
                file_path.write_bytes(downloaded)

                # URL from caption
                source_url = extract_url_from_caption(message.caption)

                safe_edit_message("⏳ Analyzing...", message.chat.id, status.message_id)

                if is_video:
                    recipe = extract_recipe_from_video(config, file_path, source_url)
                else:
                    recipe = extract_recipe_from_image(config, file_path, source_url)

                logger.info(f"Recipe extracted: {recipe.title}")
                safe_delete_message(message.chat.id, status.message_id)
                send_recipe(message, recipe)

        except Exception:
            logger.exception("Error processing document")
            safe_edit_message("❌ Document processing failed. Please try again.", message.chat.id, status.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("md:"))
    def handle_markdown_callback(call: types.CallbackQuery):
        logger.debug(f"Markdown button clicked: {call.data}")
        recipe_id = call.data[3:]
        recipe = recipe_cache.get(recipe_id)

        if not recipe:
            bot.answer_callback_query(call.id, "❌ Recipe no longer available")
            return

        base_name = sanitize_filename(recipe.title)
        markdown = format_recipe_markdown(recipe)
        md_file = io.BytesIO(markdown.encode("utf-8"))
        md_file.name = f"{base_name}.md"

        bot.send_document(call.message.chat.id, md_file, caption=f"📄 {recipe.title}")
        bot.answer_callback_query(call.id, "✅ Markdown sent")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("save:"))
    def handle_save_callback(call: types.CallbackQuery):
        logger.debug(f"Save button clicked: {call.data}")
        if not config.storage.enabled or not config.storage.path:
            bot.answer_callback_query(call.id, "❌ Saving not configured")
            return

        recipe_id = call.data[5:]
        recipe = recipe_cache.get(recipe_id)

        if not recipe:
            bot.answer_callback_query(call.id, "❌ Recipe no longer available")
            return

        try:
            md_path = save_recipe_to_file(recipe, config.storage.path)
            bot.answer_callback_query(call.id, f"✅ Saved: {md_path.name}")
            logger.info(f"Recipe saved: {md_path}")

        except Exception:
            logger.exception("Error saving")
            bot.answer_callback_query(call.id, "❌ Save failed")

    return bot


def main():
    logger.info("Recipe Collector Bot starting...")

    try:
        config = load_config()
    except FileNotFoundError:
        logger.error("config.yaml not found! Copy config.yaml.example to config.yaml")
        sys.exit(1)

    if not config.telegram.bot_token:
        logger.error("No bot token configured!")
        sys.exit(1)

    if not config.gemini.api_key:
        logger.error("No Gemini API key configured!")
        sys.exit(1)

    logger.info("Configuration loaded")

    if config.telegram.allowed_users:
        logger.info(f"Allowed users: {config.telegram.allowed_users}")
    else:
        logger.warning("WARNING: No user whitelist - anyone can use the bot!")

    if config.storage.enabled:
        logger.info(f"Storage path: {config.storage.path}")

    bot = create_bot(config)

    logger.info("Bot started! Waiting for messages...")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
