"""Foundation metadata for the backend scaffold."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FoundationInfo:
    """Small importable payload used to prove the backend package is wired."""

    service: str
    status: str
    version: str


def get_foundation_info() -> FoundationInfo:
    """Return static backend foundation metadata."""
    return FoundationInfo(service="super-ai-backend", status="ok", version="0.1.0")
