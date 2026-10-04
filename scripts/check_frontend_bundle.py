"""Fail if configured private credential values appear in built frontend assets."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def credential_values(value: object, parent: str = "") -> list[str]:
    sensitive = {"apikey", "accesskey", "secretid", "secretkey", "password", "accesstoken", "token"}
    if isinstance(value, dict):
        return [secret for key, item in value.items()
                for secret in credential_values(item, str(key).replace("_", "").lower())]
    if isinstance(value, list):
        return [secret for item in value for secret in credential_values(item, parent)]
    if parent in sensitive and isinstance(value, str) and len(value.strip()) >= 8:
        return [value]
    return []


def main() -> None:
    assets = REPO_ROOT / "apps/frontend/dist"
    if not assets.is_dir():
        raise SystemExit("Build the frontend before checking credentials.")
    secrets: list[str] = []
    for name in ("project.json", "user.project.json"):
        path = REPO_ROOT / "config" / name
        if path.exists():
            secrets.extend(credential_values(json.loads(path.read_text(encoding="utf-8"))))
    for path in assets.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            if any(secret.encode() in content or json.dumps(secret)[1:-1].encode() in content
                   for secret in secrets):
                raise SystemExit(f"Private credential found in built asset: {path.name}")
    print("Frontend bundle verified: configured private credentials are absent.")


if __name__ == "__main__":
    main()
