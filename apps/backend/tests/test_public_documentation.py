from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_public_documentation_uses_english_and_resolvable_local_links() -> None:
    documents = set(REPO_ROOT.glob("*.md"))
    documents.update(
        path
        for path in (REPO_ROOT / "docs").rglob("*.md")
        if not any(part.startswith(".") for part in path.relative_to(REPO_ROOT).parts)
    )
    for directory in (
        "apps/backend",
        "apps/frontend",
        "packages/api-contracts",
        "infra",
        "deploy/aws",
        "evaluations",
    ):
        documents.add(REPO_ROOT / directory / "README.md")

    for document in sorted(documents):
        content = document.read_text(encoding="utf-8")
        assert not re.search(r"[\u3400-\u9fff]", content), document
        for match in re.finditer(r"\[[^\]]*\]\(([^\s)]+)\)", content):
            target = match.group(1)
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (document.parent / unquote(parsed.path)).resolve()
            assert path.is_relative_to(REPO_ROOT), (document, target)
            assert path.exists(), (document, target)
