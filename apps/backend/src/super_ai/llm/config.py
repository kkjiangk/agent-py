"""Configuration loading for OpenAI-compatible LLM providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_int,
    required_str,
)


class LlmConfigurationError(RuntimeError):
    """Raised when an LLM provider cannot be configured."""


@dataclass(frozen=True, slots=True)
class LlmProviderConfig:
    """Typed runtime configuration for a configured LLM provider."""

    provider: str
    api_key: str = field(repr=False)
    base_url: str
    chat_model: str
    embedding_model: str
    embedding_dimensions: int
    rerank_model: str
    rerank_url: str
    context_window_tokens: int
    temperature: float
    timeout_seconds: float
    max_retries: int


def load_llm_provider_config(
    config_path: Path | str | None = None,
) -> LlmProviderConfig:
    """Load LLM provider configuration from the repository project config."""
    try:
        raw_config = project_config_section("llm", config_path=config_path)
        api_key = required_str(raw_config, "apiKey")

        chat_model = required_str(raw_config, "chatModel")
        model_capabilities = raw_config.get("modelCapabilities")
        if not isinstance(model_capabilities, Mapping):
            raise ProjectConfigurationError(
                "Project config field must be an object: modelCapabilities"
            )
        model_profile_raw = cast(Mapping[object, object], model_capabilities).get(chat_model)
        if not isinstance(model_profile_raw, Mapping):
            raise ProjectConfigurationError(
                f"No model capability profile configured for chatModel: {chat_model}"
            )
        model_profile = {
            str(key): value
            for key, value in cast(Mapping[object, object], model_profile_raw).items()
        }

        return LlmProviderConfig(
            provider=required_str(raw_config, "provider"),
            api_key=api_key,
            base_url=required_str(raw_config, "baseUrl"),
            chat_model=chat_model,
            embedding_model=required_str(raw_config, "embeddingModel"),
            embedding_dimensions=required_int(raw_config, "embeddingDimensions"),
            rerank_model=required_str(raw_config, "rerankModel"),
            rerank_url=required_str(raw_config, "rerankUrl"),
            context_window_tokens=required_int(model_profile, "contextWindowTokens"),
            temperature=required_float(raw_config, "temperature"),
            timeout_seconds=required_float(raw_config, "timeoutSeconds"),
            max_retries=required_int(raw_config, "maxRetries"),
        )
    except ProjectConfigurationError as exc:
        raise LlmConfigurationError(str(exc)) from exc
