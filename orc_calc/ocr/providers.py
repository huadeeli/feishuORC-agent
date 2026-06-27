from __future__ import annotations

from .cloud_paddle import CloudPaddleOCRProvider
from .local_paddle import LocalPaddleOCRProvider


def get_provider(mode: str):
    normalized = (mode or "local-fast").lower()
    if normalized == "cloud":
        return CloudPaddleOCRProvider()
    if normalized in {"fast", "local-fast", "local_fast"}:
        return LocalPaddleOCRProvider(profile="fast")
    return LocalPaddleOCRProvider()
