from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import unicodedata


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "templates.json"


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "jianhui": {
        "id": "jianhui",
        "name": "建辉送货信息",
        "sample_filename": "jianhui 模板.jpg",
        "match": {
            "width": 417,
            "height": 1280,
            "filename_keywords": ["jianhui", "建辉"],
            "ocr_keywords": ["送货日期", "结算单价", "代办税额", "结算金额"],
        },
        "aliases": {
            "gross_weight": ["毛重", "毛重*"],
            "tare_weight": ["皮重", "皮重*"],
            "unit_price": ["结算单价", "单价", "结算单价*"],
            "settlement_weight": ["结算重量", "结算重量*"],
            "tax_fee": ["代办税额", "税费", "税款合计", "代办税额*"],
        },
        "sample_values": {
            "gross_weight": "48.29",
            "tare_weight": "15.27",
            "unit_price": "1830",
            "settlement_weight": "30.84",
            "tax_fee": "894.05",
        },
    },
    "jingzhou": {
        "id": "jingzhou",
        "name": "荆州订单跟踪",
        "sample_filename": "jingzhou 模板.jpg",
        "match": {
            "width": 316,
            "height": 1280,
            "filename_keywords": ["jingzhou", "荆州"],
            "ocr_keywords": ["订单跟踪", "含税单", "税款合", "结算金"],
        },
        "aliases": {
            "gross_weight": ["毛重", "毛重:"],
            "tare_weight": ["皮重", "皮重:"],
            "unit_price": ["含税单价", "含税单", "单价"],
            "settlement_weight": ["结算重量", "结算重"],
            "tax_fee": ["税款合计", "税款合", "代办税额", "税费"],
        },
        "sample_values": {
            "gross_weight": "50.54",
            "tare_weight": "16.18",
            "unit_price": "1730",
            "settlement_weight": "32.669",
            "tax_fee": "895.33",
        },
    },
}


def load_templates() -> dict[str, dict[str, Any]]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "templates" in data:
                return {item["id"]: item for item in data["templates"]}
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    return BUILTIN_TEMPLATES


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template["id"],
            "name": template["name"],
            "aliases": template.get("aliases", {}),
            "sample_filename": template.get("sample_filename"),
        }
        for template in load_templates().values()
    ]


def get_template(template_id: str | None) -> dict[str, Any] | None:
    if not template_id or template_id == "auto":
        return None
    return load_templates().get(template_id)


def find_template_by_hint(filename: str | None = None, size: tuple[int, int] | None = None) -> dict[str, Any] | None:
    filename_lower = (filename or "").lower()
    for template in load_templates().values():
        match = template.get("match", {})
        if size and match.get("width") == size[0] and match.get("height") == size[1]:
            return template
        for keyword in match.get("filename_keywords", []):
            if keyword.lower() in filename_lower:
                return template
    return None


def find_template_by_ocr_text(texts: list[str]) -> dict[str, Any] | None:
    haystack = _normalize_text("".join(texts))
    if not haystack:
        return None

    best_template: dict[str, Any] | None = None
    best_score = 0
    for template in load_templates().values():
        keywords = template.get("match", {}).get("ocr_keywords", [])
        score = sum(1 for keyword in keywords if _normalize_text(str(keyword)) in haystack)
        if score > best_score:
            best_score = score
            best_template = template
    return best_template if best_score >= 2 else None


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return text.replace(" ", "").replace("\t", "").replace("*", "")
