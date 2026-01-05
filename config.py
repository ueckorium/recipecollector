"""Konfigurationsmanagement für Recipe Collector Bot."""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
class Config:
    telegram: TelegramConfig
    gemini: GeminiConfig
    storage: StorageConfig


def _expand_env(value: str) -> str:
    """Ersetzt ${ENV_VAR} mit Umgebungsvariablen."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        return os.environ.get(env_var, "")
    return value


def load_config(config_path: Path | None = None) -> Config:
    """Lädt Konfiguration aus YAML-Datei."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    telegram = TelegramConfig(
        bot_token=_expand_env(raw["telegram"]["bot_token"]),
        allowed_users=raw["telegram"].get("allowed_users", []),
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

    return Config(telegram=telegram, gemini=gemini, storage=storage)
