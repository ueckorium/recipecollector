"""Configuration management for Recipe Collector Bot."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class TelegramConfig:
    bot_token: str
    allowed_users: list[int] = field(default_factory=list)


@dataclass
class GeminiConfig:
    api_key: str
    model: str = "gemini-2.0-flash"


@dataclass
class StorageConfig:
    enabled: bool = False
    path: Path | None = None


@dataclass
class OutputConfig:
    format: str = "markdown"  # "markdown" or "cooklang"


# Default prompt for recipe extraction
DEFAULT_EXTRACTION_PROMPT = """Analyze ALL provided sources and extract the recipe completely.

SOURCE PRIORITIZATION (in case of conflicts):
1. Subtitles/Captions (most accurate source for spoken quantities)
2. Video description (often contains complete ingredient lists)
3. Video content (visual information)
4. Webpage text (context)

Respond ONLY with a JSON object in this format:
{
  "title": "Name of the dish",
  "servings": "4 servings",
  "prep_time": "15 min",
  "cook_time": "30 min",
  "total_time": "45 min",
  "difficulty": "medium",
  "tags": ["italian", "pasta", "vegetarian"],
  "ingredients": [
    "## For the sauce",
    "200g Guanciale",
    "4 egg yolks",
    "## For the pasta",
    "400g Spaghetti",
    "Salt"
  ],
  "instructions": [
    "Cook pasta in plenty of salted water until al dente (about 8-10 min)",
    "Cut guanciale into cubes and fry until crispy over medium heat",
    "Mix egg yolks with grated Pecorino"
  ],
  "equipment": ["large pot", "pan", "grater"],
  "notes": ["Pancetta can substitute for Guanciale", "Save pasta water for binding"]
}

IMPORTANT - COMPLETENESS:
- Extract ALL mentioned ingredients with EXACT quantities
- When quantities are mentioned (spoken, written, displayed), copy them EXACTLY
- Mark ingredient group headers with "## " (e.g., "## For the dough")
- List each preparation step individually and in detail
- Only list equipment if special tools are required
- Use notes for tips, variations, substitutions

CONVERSIONS:
- Quantities in metric units, original in parentheses: "240ml (1 cup) milk"
- Temperatures in Celsius with original: "180°C (350°F)"
- Translate "pinch", "dash" etc. appropriately

DIFFICULTY LEVEL:
- "easy": Few ingredients, simple techniques, under 30 min
- "medium": Multiple steps, some experience helpful
- "hard": Complex techniques, many components, time-consuming

TIMES:
- prep_time: Active preparation time (cutting, mixing)
- cook_time: Time at stove/oven
- total_time: Total time including resting periods
- If only total time is known: only specify total_time

RULES:
- Omit missing fields (don't use null or empty)
- ONLY the JSON, no other text!"""


@dataclass
class PromptsConfig:
    extraction: str = DEFAULT_EXTRACTION_PROMPT


@dataclass
class Config:
    telegram: TelegramConfig
    gemini: GeminiConfig
    storage: StorageConfig
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def _expand_env(value: str) -> str:
    """Replaces ${ENV_VAR} with environment variables."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def _validate_user_ids(raw_users: list) -> list[int]:
    """Validates and converts user IDs to integers."""
    valid_ids = []
    for user in raw_users:
        try:
            if isinstance(user, int):
                valid_ids.append(user)
            elif isinstance(user, str) and user.strip().isdigit():
                valid_ids.append(int(user.strip()))
        except (ValueError, TypeError):
            continue
    return valid_ids


def load_config(config_path: Path | None = None) -> Config:
    """Loads configuration from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    telegram = TelegramConfig(
        bot_token=_expand_env(raw["telegram"]["bot_token"]),
        allowed_users=_validate_user_ids(raw["telegram"].get("allowed_users", [])),
    )

    gemini = GeminiConfig(
        api_key=_expand_env(raw["gemini"]["api_key"]),
        model=raw["gemini"].get("model", "gemini-1.5-flash"),
    )

    storage_raw = raw.get("storage", {})
    storage = StorageConfig(
        enabled=storage_raw.get("enabled", False),
        path=Path(storage_raw["path"]) if storage_raw.get("path") else None,
    )

    prompts_raw = raw.get("prompts", {})
    prompts = PromptsConfig(
        extraction=prompts_raw.get("extraction", DEFAULT_EXTRACTION_PROMPT),
    )

    output_raw = raw.get("output", {})
    output_format = output_raw.get("format", "markdown").lower()
    if output_format not in ("markdown", "cooklang"):
        logger.warning(f"Invalid output format '{output_format}', defaulting to 'markdown'")
        output_format = "markdown"
    output = OutputConfig(format=output_format)

    return Config(telegram=telegram, gemini=gemini, storage=storage, prompts=prompts, output=output)
