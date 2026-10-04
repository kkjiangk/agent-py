"""User-scoped chat prompt and Skill assembly helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import cast

import yaml

DEFAULT_CHAT_PROMPT_LABEL = "默认系统提示词"
DEFAULT_CHAT_PROMPT_CONTENT = (
    "你是一个可靠的中文 AI 助手。除非专业术语需要英文，否则使用简体中文清晰回答。"
)
MAX_CHAT_PROMPT_CONTENT_LENGTH = 12000
MAX_CHAT_SKILL_BYTES = 65536
MAX_CHAT_SKILL_NAME_LENGTH = 64
MAX_CHAT_SKILL_DESCRIPTION_LENGTH = 1024
_SKILL_FRONTMATTER_PATTERN = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", re.DOTALL)

MANDATORY_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Use tools only when useful, cite knowledge sources, "
    "and never invent tool results. For CLS log queries, prefer SearchLog directly "
    "with explicit Region, TopicId, From, To, Query, and Limit values in milliseconds. "
    "Do not call time-conversion or topic-discovery helper tools unless required. "
    "Before any time-based query, call get_current_time first and use its returned "
    "timestamp."
)


@dataclass(frozen=True, slots=True)
class SelectedChatSkill:
    """A user-selected Skill available for progressive disclosure."""

    name: str
    description: str
    content: str


@dataclass(frozen=True, slots=True)
class ValidatedChatSkill:
    """Validated Agent Skills metadata and canonical Markdown content."""

    filename: str
    name: str
    description: str
    content: str


def build_chat_system_prompt(
    *,
    prompt_content: str,
    skills: Sequence[SelectedChatSkill] = (),
) -> str:
    """Build the system prompt passed into the LangChain Agent."""
    sections = [
        MANDATORY_CHAT_SYSTEM_PROMPT,
        "用户选择的系统提示词：\n" + prompt_content.strip(),
    ]
    if skills:
        skill_catalog = "\n".join(
            f"- **{skill.name}**: {skill.description}" for skill in skills
        )
        sections.append(
            "\n".join(
                [
                    "## Available Skills",
                    skill_catalog,
                    "以上仅为当前会话允许使用的 Skill。判断用户任务与某个 Skill 的描述匹配时，"
                    "必须先调用 `load_skill` 并传入该 Skill 的 name，再依据返回的完整指令回答。"
                    "不要猜测或声称已加载未调用的 Skill。",
                ]
            )
        )
    return "\n\n".join(section for section in sections if section.strip())


def validate_chat_prompt_content(label: str, content: str) -> tuple[str, str]:
    """Normalize and validate user-owned prompt input."""
    normalized_label = label.strip()
    normalized_content = content.strip()
    if not normalized_label or not normalized_content:
        raise ValueError("系统提示词名称和内容都不能为空。")
    if len(normalized_label) > 160 or len(normalized_content) > MAX_CHAT_PROMPT_CONTENT_LENGTH:
        raise ValueError("系统提示词名称不能超过 160 字符，内容不能超过 12000 字符。")
    return normalized_label, normalized_content


def validate_skill_upload(filename: str | None, content: bytes) -> ValidatedChatSkill:
    """Validate an uploaded Markdown file against the Agent Skills metadata contract."""
    normalized_filename = PurePath(filename or "").name
    if normalized_filename != (filename or "") or normalized_filename != "SKILL.md":
        raise ValueError("Skill 文件名必须严格为 SKILL.md。")
    if not content:
        raise ValueError("Skill 文件不能为空，请上传 UTF-8 Markdown 文本。")
    if len(content) > MAX_CHAT_SKILL_BYTES:
        raise ValueError("Skill 文件不能超过 64 KB。")
    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Skill 文件必须是 UTF-8 编码的 Markdown 文本。") from exc
    normalized_content = decoded.strip()
    if not normalized_content:
        raise ValueError("Skill 文件不能为空，请写入可读的 Markdown 指令。")
    match = _SKILL_FRONTMATTER_PATTERN.match(normalized_content)
    if match is None:
        raise ValueError("SKILL.md 必须以包含 name 和 description 的 YAML frontmatter 开头。")
    try:
        parsed_metadata: object = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise ValueError("SKILL.md 的 YAML frontmatter 格式无效。") from exc
    if not isinstance(parsed_metadata, Mapping):
        raise ValueError("SKILL.md 的 YAML frontmatter 必须是键值对象。")
    metadata = cast(Mapping[object, object], parsed_metadata)
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not _is_valid_skill_name(name.strip()):
        raise ValueError(
            "Skill name 必须为 1-64 个小写字母、数字或单连字符，且不能以连字符开头或结尾。"
        )
    normalized_name = name.strip()
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Skill description 不能为空，且应说明能力和适用场景。")
    normalized_description = description.strip()
    if len(normalized_description) > MAX_CHAT_SKILL_DESCRIPTION_LENGTH:
        raise ValueError("Skill description 不能超过 1024 个字符。")
    return ValidatedChatSkill(
        filename=normalized_filename,
        name=normalized_name,
        description=normalized_description,
        content=normalized_content,
    )


def _is_valid_skill_name(name: str) -> bool:
    if not name or len(name) > MAX_CHAT_SKILL_NAME_LENGTH:
        return False
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False
    return all(
        character == "-" or character.isdigit() or ("a" <= character <= "z")
        for character in name
    )
