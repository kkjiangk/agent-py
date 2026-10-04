"""Typed HTTP request schemas shared by API routers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email: str
    display_name: str = Field(alias="displayName")
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateChatSessionRequest(BaseModel):
    title: str | None = None


class AppendChatMessageRequest(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class StreamChatMessageRequest(BaseModel):
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class UpdateChatMemoryRequest(BaseModel):
    mode: Literal["every_30_turns", "context_70_percent", "manual"]


class UpdateChatAssemblyConfigurationRequest(BaseModel):
    system_prompt_id: str = Field(alias="systemPromptId")
    skill_ids: list[str] = Field(alias="skillIds")


class CreateChatPromptRequest(BaseModel):
    label: str
    content: str


class UpdateChatPromptRequest(BaseModel):
    label: str
    content: str


class CreateAiopsDiagnosticRequest(BaseModel):
    query: str
    alert: dict[str, object] = Field(default_factory=dict)


class CreateRemediationApprovalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tool_name: str = Field(alias="toolName", min_length=1, max_length=160)
    arguments: dict[str, object] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=4000)
    risk_level: Literal["low", "medium", "high", "critical"] = Field(alias="riskLevel")


class DecideRemediationApprovalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    decision: Literal["approved", "rejected"]
    decision_note: str | None = Field(default=None, alias="decisionNote", max_length=2000)


class UpsertFeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_type: Literal["chat_message", "citation", "diagnostic_step", "diagnostic_report"] = (
        Field(alias="targetType")
    )
    target_id: str = Field(alias="targetId", min_length=1, max_length=160)
    subject_id: str | None = Field(default=None, alias="subjectId", max_length=160)
    rating: Literal["positive", "negative"]
    reason: str | None = Field(default=None, max_length=80)
    comment: str | None = Field(default=None, max_length=2000)
    correction: str | None = Field(default=None, max_length=4000)


class McpConnectionMutationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    transport: Literal["sse", "streamable_http"]
    url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    timeout_seconds: int = Field(default=15, alias="timeoutSeconds", ge=1, le=300)
    retries: int = Field(default=1, ge=0, le=5)
