from pathlib import Path

from super_ai.chat.configuration import MAX_CHAT_SKILL_BYTES, validate_skill_upload


def test_repository_contains_five_uploadable_skill_examples() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    examples_dir = repository_root / "docs" / "examples" / "skills"
    skill_files = sorted(examples_dir.glob("*/SKILL.md"))

    assert len(skill_files) == 5
    for path in skill_files:
        content = path.read_bytes()
        validated = validate_skill_upload(path.name, content)

        assert validated.filename == "SKILL.md"
        assert validated.name == path.parent.name
        assert validated.description
        assert validated.content.startswith("---\n")
        assert 0 < len(content) < MAX_CHAT_SKILL_BYTES


def test_skill_upload_requires_standard_frontmatter() -> None:
    invalid_files = (
        ("OpsSKILL.md", b"---\nname: ops\ndescription: Ops\n---\n# Ops"),
        ("SKILL.md", b"# Missing frontmatter"),
        ("SKILL.md", b"---\nname: Bad_Name\ndescription: Ops\n---\n# Ops"),
        ("SKILL.md", b"---\nname: ops\n---\n# Ops"),
    )

    for filename, content in invalid_files:
        try:
            validate_skill_upload(filename, content)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid Skill upload: {filename} {content!r}")
