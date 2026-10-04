from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from super_ai.llm import (
    EmbeddingModel,
    LlmConfigurationError,
    QwenOpenAIProvider,
    load_llm_provider_config,
)


class FakeChatModel:
    def __init__(self, response: object | None = "ok", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        if self.error is not None:
            raise self.error
        return self.response


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[1.0, 0.0, 0.5] for _text in texts]


class FakeAsyncEmbeddingClient:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def create(self, *, input: list[str], **_kwargs: object) -> dict[str, object]:
        self.inputs.append(input)
        return {
            "data": [
                {"embedding": [float(text.removeprefix("text-"))]}
                for text in input
            ]
        }


def test_loads_tracked_qwen_defaults() -> None:
    config = load_llm_provider_config()

    assert config.provider == "qwen-openai"
    assert config.api_key.startswith("sk-")
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config.chat_model == "qwen3.7-max"
    assert config.embedding_model == "text-embedding-v4"
    assert config.embedding_dimensions == 1024
    assert config.rerank_model == "qwen3-vl-rerank"
    assert config.rerank_url.endswith("/text-rerank/text-rerank")
    assert config.context_window_tokens == 1_000_000
    assert config.temperature == 0.2
    assert config.timeout_seconds == 120.0
    assert config.max_retries == 2


def test_loads_explicit_project_config_file(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="test-secret",
        base_url="https://example.test/v1",
        chat_model="qwen-test-chat",
        embedding_model="qwen-test-embedding",
        embedding_dimensions=768,
        rerank_model="qwen-test-rerank",
        temperature=0.7,
        timeout_seconds=45,
        max_retries=4,
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.api_key == "test-secret"
    assert config.base_url == "https://example.test/v1"
    assert config.chat_model == "qwen-test-chat"
    assert config.embedding_model == "qwen-test-embedding"
    assert config.embedding_dimensions == 768
    assert config.rerank_model == "qwen-test-rerank"
    assert config.temperature == 0.7
    assert config.timeout_seconds == 45.0
    assert config.max_retries == 4


def test_merges_user_project_config_file(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        api_key="",
        chat_model="",
        embedding_model="",
    )
    (tmp_path / "user.project.json").write_text(
        json.dumps(
            {
                "llm": {
                    "apiKey": "merged-secret",
                    "chatModel": "merged-chat",
                    "embeddingModel": "merged-embedding",
                    "modelCapabilities": {
                        "merged-chat": {"contextWindowTokens": 262144}
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_llm_provider_config(config_path=config_path)

    assert config.api_key == "merged-secret"
    assert config.chat_model == "merged-chat"
    assert config.embedding_model == "merged-embedding"
    assert config.context_window_tokens == 262144
    assert config.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_missing_api_key_fails_safely(
    tmp_path: Path,
) -> None:
    config_path = _write_config(tmp_path, api_key="")

    with pytest.raises(LlmConfigurationError) as exc_info:
        load_llm_provider_config(config_path=config_path)

    message = str(exc_info.value)
    assert "apiKey" in message
    assert "sk-" not in message


def test_chat_model_requires_matching_capability_profile(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, api_key="test-secret")
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    raw_config["llm"]["chatModel"] = "unprofiled-model"
    config_path.write_text(json.dumps(raw_config), encoding="utf-8")

    with pytest.raises(LlmConfigurationError, match="unprofiled-model"):
        load_llm_provider_config(config_path=config_path)


def test_provider_constructs_model_with_config() -> None:
    config = load_llm_provider_config()
    captured: dict[str, Any] = {}

    def fake_factory(factory_config: object) -> FakeChatModel:
        captured["config"] = factory_config
        return FakeChatModel()

    provider = QwenOpenAIProvider(config=config, model_factory=fake_factory)

    model = provider.create_chat_model()

    assert isinstance(model, FakeChatModel)
    assert captured["config"] is config


def test_provider_constructs_embedding_model_with_config() -> None:
    config = load_llm_provider_config()
    captured: dict[str, object] = {}

    def fake_embedding_factory(factory_config: object) -> EmbeddingModel:
        captured["config"] = factory_config
        return FakeEmbeddingModel()

    provider = QwenOpenAIProvider(
        config=config,
        model_factory=lambda _: FakeChatModel(),
        embedding_factory=fake_embedding_factory,
    )

    model = provider.create_embedding_model()

    assert isinstance(model, FakeEmbeddingModel)
    assert captured["config"] is config


@pytest.mark.asyncio
async def test_default_embedding_model_preserves_raw_qwen_inputs_and_batches_by_ten() -> None:
    config = load_llm_provider_config()
    provider = QwenOpenAIProvider(config=config, model_factory=lambda _: FakeChatModel())

    model = provider.create_embedding_model()
    embedding_model = cast(Any, model)
    fake_client = FakeAsyncEmbeddingClient()
    embedding_model.async_client = fake_client
    texts = [f"text-{index}" for index in range(11)]

    vectors = await embedding_model.aembed_documents(texts)

    assert embedding_model.check_embedding_ctx_length is False
    assert embedding_model.dimensions == config.embedding_dimensions
    assert embedding_model.chunk_size == 10
    assert fake_client.inputs == [texts[:10], texts[10:]]
    assert vectors == [[float(index)] for index in range(11)]


@pytest.mark.asyncio
async def test_readiness_succeeds_without_exposing_secret() -> None:
    config = load_llm_provider_config()
    fake_model = FakeChatModel(response="ready")
    provider = QwenOpenAIProvider(config=config, model_factory=lambda _: fake_model)

    result = await provider.check_readiness()

    assert result.ok is True
    assert result.provider == "qwen-openai"
    assert result.model == "qwen3.7-max"
    assert result.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert result.error is None
    assert result.latency_ms >= 0
    assert config.api_key not in repr(result)
    assert fake_model.inputs


@pytest.mark.asyncio
async def test_readiness_failure_is_safe() -> None:
    config = load_llm_provider_config()
    provider = QwenOpenAIProvider(
        config=config,
        model_factory=lambda _: FakeChatModel(error=RuntimeError("provider unavailable")),
    )

    result = await provider.check_readiness()

    assert result.ok is False
    assert result.error == "provider unavailable"
    assert config.api_key not in repr(result)


def test_provider_source_does_not_import_dashscope() -> None:
    source_root = Path("src/super_ai/llm")
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_root.glob("*.py"))

    assert "dashscope" not in source.lower()


def _write_config(
    tmp_path: Path,
    *,
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    chat_model: str = "qwen3.7-max",
    embedding_model: str = "text-embedding-v4",
    embedding_dimensions: int = 1024,
    rerank_model: str = "qwen3-vl-rerank",
    rerank_url: str = "https://example.test/rerank",
    context_window_tokens: int = 1_000_000,
    temperature: float = 0.2,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> Path:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "qwen-openai",
                    "apiKey": api_key,
                    "baseUrl": base_url,
                    "chatModel": chat_model,
                    "embeddingModel": embedding_model,
                    "embeddingDimensions": embedding_dimensions,
                    "rerankModel": rerank_model,
                    "rerankUrl": rerank_url,
                    "modelCapabilities": {
                        chat_model: {"contextWindowTokens": context_window_tokens}
                    },
                    "temperature": temperature,
                    "timeoutSeconds": timeout_seconds,
                    "maxRetries": max_retries,
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path
