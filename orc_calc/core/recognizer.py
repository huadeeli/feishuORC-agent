from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .calculator import RECOGNIZED_FIELDS, calculation_payload
from .image_meta import jpeg_size
from .templates import find_template_by_hint, find_template_by_ocr_text, get_template


VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float = 0.0
    box: list[list[float]] | None = None


@dataclass(slots=True)
class RecognizedField:
    key: str
    label: str
    value: str = ""
    confidence: float = 0.0
    source: str = "missing"
    raw_text: str = ""


LABELS = {
    "gross_weight": "毛重",
    "tare_weight": "皮重",
    "unit_price": "单价",
    "settlement_weight": "结算重量",
    "tax_fee": "税费",
}


DEFAULT_ALIASES = {
    "gross_weight": ["毛重", "毛重*"],
    "tare_weight": ["皮重", "皮重*"],
    "unit_price": ["单价", "结算单价", "含税单价", "含税单"],
    "settlement_weight": ["结算重量", "结算重"],
    "tax_fee": ["税费", "代办税额", "代办税额*", "税款合计", "税款合"],
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return text.replace(" ", "").replace("\t", "")


def line_to_dict(line: OCRLine) -> dict[str, Any]:
    return asdict(line)


def field_to_dict(field: RecognizedField) -> dict[str, Any]:
    return asdict(field)


def _extract_value_near_alias(lines: list[OCRLine], aliases: Iterable[str]) -> tuple[str, float, str] | None:
    normalized_aliases = [normalize_text(alias).replace("*", "") for alias in aliases]

    for index, line in enumerate(lines):
        text = normalize_text(line.text)
        text_no_star = text.replace("*", "")
        for alias in normalized_aliases:
            if not alias or alias not in text_no_star:
                continue

            after_alias = text_no_star.split(alias, 1)[-1]
            number = VALUE_RE.search(after_alias)
            if number:
                return number.group(0), line.confidence, line.text

            for next_line in lines[index + 1:index + 3]:
                next_number = VALUE_RE.search(normalize_text(next_line.text))
                if next_number:
                    confidence = min(line.confidence or 0.0, next_line.confidence or line.confidence or 0.0)
                    return next_number.group(0), confidence, f"{line.text} {next_line.text}"
    return None


def extract_fields_from_lines(lines: list[OCRLine], template: dict[str, Any] | None) -> list[RecognizedField]:
    aliases_by_key = (template or {}).get("aliases", {})
    fields: list[RecognizedField] = []
    for key in RECOGNIZED_FIELDS:
        aliases = _field_aliases(key, aliases_by_key)
        match = _extract_value_near_alias(lines, aliases)
        if match:
            value, confidence, raw_text = match
            fields.append(
                RecognizedField(
                    key=key,
                    label=LABELS[key],
                    value=value,
                    confidence=round(float(confidence or 0.0), 4),
                    source="ocr",
                    raw_text=raw_text,
                )
            )
        else:
            fields.append(RecognizedField(key=key, label=LABELS[key]))
    return fields


def _field_aliases(key: str, aliases_by_key: dict[str, Any]) -> list[str]:
    aliases = list(DEFAULT_ALIASES.get(key, [LABELS[key]]))
    for alias in aliases_by_key.get(key, []):
        if alias not in aliases:
            aliases.append(alias)
    return aliases


def fields_to_values(fields: list[RecognizedField], manual_values: dict[str, Any] | None = None) -> dict[str, Any]:
    values = {field.key: field.value for field in fields}
    if manual_values:
        values.update(manual_values)
    return values


def sample_fields(template: dict[str, Any], source: str) -> list[RecognizedField]:
    values = template.get("sample_values", {})
    return [
        RecognizedField(
            key=key,
            label=LABELS[key],
            value=str(values.get(key, "")),
            confidence=0.99 if values.get(key) else 0.0,
            source=source if values.get(key) else "missing",
            raw_text=f"{LABELS[key]} {values.get(key, '')}".strip(),
        )
        for key in RECOGNIZED_FIELDS
    ]


def recognize_from_ocr_lines(
    lines: list[OCRLine],
    *,
    image_path: str | Path | None = None,
    image_filename: str | None = None,
    template_id: str | None = None,
    provider_name: str = "unknown",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings = list(warnings or [])
    size = None
    if image_path:
        try:
            size = jpeg_size(image_path)
        except OSError:
            size = None

    explicit_template = get_template(template_id)
    hint_template = find_template_by_hint(image_filename or (Path(image_path).name if image_path else None), size)
    text_template = find_template_by_ocr_text([line.text for line in lines])
    template = explicit_template or hint_template or text_template
    fields = extract_fields_from_lines(lines, template)

    if not template and lines:
        missing_labels = [field.label for field in fields if not field.value]
        if missing_labels:
            warnings.append(f"模板未匹配，已按通用字段别名提取；仍未识别字段：{'、'.join(missing_labels)}。")

    values = fields_to_values(fields)
    calculation = calculation_payload(values)
    return {
        "template": {"id": template["id"], "name": template["name"]} if template else None,
        "provider": provider_name,
        "fields": [field_to_dict(field) for field in fields],
        "calculation": calculation,
        "ocr_lines": [line_to_dict(line) for line in lines],
        "warnings": warnings,
    }
