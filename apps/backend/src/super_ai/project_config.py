"""Repository project configuration loader."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

DEFAULT_PROJECT_CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "project.json"
DEFAULT_USER_PROJECT_CONFIG_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "user.project.json"
)


class ProjectConfigurationError(RuntimeError):
    """Raised when repository configuration cannot be loaded."""


def load_project_config(
    config_path: Path | str | None = None,
    *,
    user_config_path: Path | str | None = None,
) -> Mapping[str, Any]:
    """Load the repository-level JSON configuration file with user overrides."""
    path = Path(config_path) if config_path is not None else DEFAULT_PROJECT_CONFIG_PATH
    config = _read_json_object(path)
    override_path = _default_user_config_path(path, user_config_path)
    if override_path.exists():
        override = _read_json_object(override_path)
        return _deep_merge(config, override)
    return config


def _read_json_object(path: Path) -> Mapping[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectConfigurationError(f"Unable to read project config: {path}") from exc

    try:
        parsed: object = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ProjectConfigurationError(f"Invalid project config JSON: {path}") from exc

    if not isinstance(parsed, dict):
        raise ProjectConfigurationError(f"Project config must be a JSON object: {path}")
    return cast(Mapping[str, Any], parsed)


def _default_user_config_path(
    base_config_path: Path,
    user_config_path: Path | str | None,
) -> Path:
    if user_config_path is not None:
        return Path(user_config_path)
    if base_config_path == DEFAULT_PROJECT_CONFIG_PATH:
        return DEFAULT_USER_PROJECT_CONFIG_PATH
    return base_config_path.with_name("user.project.json")


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> Mapping[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(
                cast(Mapping[str, Any], current),
                cast(Mapping[str, Any], value),
            )
        else:
            merged[key] = value
    return merged


def project_config_section(
    name: str,
    *,
    config_path: Path | str | None = None,
) -> Mapping[str, Any]:
    """Return a required object section from the project config."""
    config = load_project_config(config_path)
    section = config.get(name)
    if not isinstance(section, dict):
        raise ProjectConfigurationError(f"Project config section must be an object: {name}")
    return cast(Mapping[str, Any], section)


def required_str(raw_config: Mapping[str, Any], key: str) -> str:
    value = raw_config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigurationError(f"Project config field must be a non-empty string: {key}")
    return value.strip()


def required_float(raw_config: Mapping[str, Any], key: str) -> float:
    value = raw_config.get(key)
    if not isinstance(value, (int, float)):
        raise ProjectConfigurationError(f"Project config field must be numeric: {key}")
    return float(value)


def required_int(raw_config: Mapping[str, Any], key: str) -> int:
    value = raw_config.get(key)
    if not isinstance(value, int):
        raise ProjectConfigurationError(f"Project config field must be an integer: {key}")
    return value


def required_dict(raw_config: Mapping[str, Any], key: str) -> dict[str, int | float | str]:
    value = raw_config.get(key)
    if not isinstance(value, dict):
        raise ProjectConfigurationError(f"Project config field must be an object: {key}")
    result: dict[str, int | float | str] = {}
    mapping = cast(Mapping[object, object], value)
    for item_key, item_value in mapping.items():
        if not isinstance(item_key, str) or not isinstance(item_value, (int, float, str)):
            raise ProjectConfigurationError(
                f"Project config object values must be strings or numbers: {key}"
            )
        result[item_key] = item_value
    return result
