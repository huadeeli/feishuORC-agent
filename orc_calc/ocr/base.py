from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from orc_calc.core.recognizer import OCRLine


@dataclass(slots=True)
class OCRProviderResult:
    provider: str
    lines: list[OCRLine]
    warnings: list[str]
    metadata: dict[str, object] = field(default_factory=dict)


class OCRProvider:
    name = "base"

    def recognize(self, image_path: str | Path, *, image_filename: str | None = None) -> OCRProviderResult:
        raise NotImplementedError
