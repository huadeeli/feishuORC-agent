from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from . import __version__
from .core.calculator import FIELD_LABELS, RECOGNIZED_FIELDS, calculation_payload
from .core.recognizer import recognize_from_ocr_lines
from .core.templates import PROJECT_ROOT, list_templates
from .ocr.cloud_paddle import check_cloud_ocr, cloud_runtime_status
from .ocr.base import OCRProviderResult
from .ocr.local_paddle import check_ocr_model, ocr_runtime_status
from .ocr.providers import get_provider


RUNTIME_UPLOADS = Path(tempfile.gettempdir()) / "orc_calc_uploads"
API_VERSION = "v1"


class RecognitionError(RuntimeError):
    pass


def health() -> dict[str, Any]:
    return {
        "ok": True,
        "name": "废纸 OCR 计算器",
        "version": __version__,
        "api_version": API_VERSION,
        "service": "local",
        **ocr_runtime_status(),
    }


def ocr_check() -> dict[str, Any]:
    return {
        "ok": True,
        "name": "废纸 OCR 计算器",
        "version": __version__,
        "api_version": API_VERSION,
        "service": "local",
        **check_ocr_model(force=True),
    }


def cloud_check(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    image_path = payload.get("image_path") or payload.get("image")
    if image_path:
        return {"ok": True, **check_cloud_ocr(str(image_path))}
    return {"ok": True, **cloud_runtime_status()}


def templates() -> dict[str, Any]:
    return {"templates": list_templates()}


def calculate(payload: dict[str, Any]) -> dict[str, Any]:
    values = payload.get("values", payload)
    if not isinstance(values, dict):
        raise ValueError("values must be an object")
    return calculation_payload(values)


def recognize(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("ocr", payload.get("mode", os.getenv("ORC_OCR_MODE", "auto"))))
    template_id = payload.get("template_id") or payload.get("template") or "auto"
    image_filename = payload.get("filename") or payload.get("image_filename")

    image_path = payload.get("image_path")
    temp_path: Path | None = None
    if not image_path:
        image_base64 = payload.get("image_base64") or payload.get("image")
        if not image_base64:
            raise ValueError("image_path or image_base64 is required")
        temp_path = _save_base64_image(str(image_base64), image_filename)
        image_path = str(temp_path)

    path = Path(str(image_path))
    if not path.exists():
        raise FileNotFoundError(str(path))

    started = time.monotonic()
    attempts: list[dict[str, Any]] = []
    for attempt_mode in _recognition_modes(mode):
        attempt_started = time.monotonic()
        provider_result = _run_provider(attempt_mode, path, image_filename or path.name)
        elapsed_ms = round((time.monotonic() - attempt_started) * 1000)
        attempt = {
            "mode": attempt_mode,
            "provider": provider_result.provider,
            "model": provider_result.metadata.get("model", ""),
            "line_count": len(provider_result.lines),
            "elapsed_ms": elapsed_ms,
            "warnings": list(provider_result.warnings),
        }
        if not provider_result.lines:
            attempt["ok"] = False
            attempt["reason"] = "OCR 返回 0 行文字"
            attempts.append(attempt)
            continue

        result = recognize_from_ocr_lines(
            provider_result.lines,
            image_path=path,
            image_filename=image_filename or path.name,
            template_id=str(template_id),
            provider_name=provider_result.provider,
            warnings=provider_result.warnings,
        )
        missing_fields = _missing_required_fields(result)
        attempt["missing_fields"] = missing_fields
        attempt["ok"] = not missing_fields
        if missing_fields:
            labels = "、".join(FIELD_LABELS[key] for key in missing_fields)
            attempt["reason"] = f"缺少关键字段：{labels}"
            attempts.append(attempt)
            continue

        attempts.append(attempt)
        result["ocr"] = {
            "requested_mode": mode,
            "selected_mode": attempt_mode,
            "provider": provider_result.provider,
            "model": provider_result.metadata.get("model", ""),
            "fallback_used": attempt_mode != _recognition_modes(mode)[0],
            "attempts": attempts,
            "total_elapsed_ms": round((time.monotonic() - started) * 1000),
        }
        if temp_path:
            result["uploaded_filename"] = image_filename or temp_path.name
        return result

    detail = "; ".join(
        f"{item['mode']}: {item.get('reason') or ', '.join(item.get('warnings') or []) or '识别失败'}"
        for item in attempts
    )
    raise RecognitionError(f"OCR 未取得完整结果，已停止发送。{detail}")


def warmup(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    mode = str(payload.get("ocr") or "local-fast")
    image_path = payload.get("image_path")
    if image_path:
        path = Path(str(image_path))
    else:
        samples = sorted(PROJECT_ROOT.glob("*.jpg"))
        if not samples:
            raise FileNotFoundError("未找到用于 OCR 预热的样图")
        path = samples[0]
    started = time.monotonic()
    provider_result = _run_provider(mode, path, path.name)
    if not provider_result.lines:
        detail = "；".join(provider_result.warnings) or "OCR 返回 0 行文字"
        raise RecognitionError(f"OCR 预热失败：{detail}")
    return {
        "ok": True,
        "mode": mode,
        "provider": provider_result.provider,
        "model": provider_result.metadata.get("model", ""),
        "line_count": len(provider_result.lines),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def _run_provider(mode: str, path: Path, image_filename: str) -> OCRProviderResult:
    try:
        return get_provider(mode).recognize(path, image_filename=image_filename)
    except Exception as exc:
        return OCRProviderResult(
            provider=f"{mode}-provider",
            lines=[],
            warnings=[f"{type(exc).__name__}: {exc}"],
            metadata={"mode": mode},
        )


def _recognition_modes(mode: str) -> list[str]:
    normalized = (mode or "auto").strip().lower()
    if normalized != "auto":
        return [normalized]
    primary = os.getenv("ORC_OCR_PRIMARY", "cloud").strip().lower() or "cloud"
    fallback_raw = os.getenv("ORC_OCR_FALLBACK", "local-fast")
    candidates = [primary, *(item.strip().lower() for item in fallback_raw.split(","))]
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result or ["cloud", "local-fast"]


def _missing_required_fields(result: dict[str, Any]) -> list[str]:
    values = {
        str(field.get("key")): str(field.get("value") or "").strip()
        for field in result.get("fields", [])
        if isinstance(field, dict)
    }
    return [key for key in RECOGNIZED_FIELDS if not values.get(key)]


def api_spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "废纸 OCR 计算器 API",
            "version": __version__,
            "description": "本地计算器核心接口，供网页、CLI、OpenClaw 或其他 Agent 调用。",
        },
        "paths": {
            "/api/v1/health": {"get": {"summary": "健康检查"}},
            "/api/v1/templates": {"get": {"summary": "模板列表"}},
            "/api/v1/cloud-check": {"get": {"summary": "Cloud OCR check"}},
            "/api/v1/recognize": {
                "post": {
                    "summary": "识别图片并计算",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {
                                    "ocr": "local",
                                    "template_id": "auto",
                                    "filename": "jianhui 模板.jpg",
                                    "image_base64": "...",
                                }
                            }
                        }
                    },
                }
            },
            "/api/v1/warmup": {"post": {"summary": "预热本地 PP-OCRv5 mobile 模型"}},
            "/api/v1/calculate": {
                "post": {
                    "summary": "按字段值计算",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "example": {
                                    "values": {
                                        "gross_weight": "50.54",
                                        "tare_weight": "16.18",
                                        "unit_price": "1730",
                                        "settlement_weight": "32.669",
                                        "tax_fee": "895.33",
                                        "service_fee_per_ton": "0",
                                        "broker_fee_per_ton": "0",
                                    }
                                }
                            }
                        }
                    },
                }
            },
        },
    }


def _save_base64_image(image_base64: str, filename: str | None) -> Path:
    RUNTIME_UPLOADS.mkdir(parents=True, exist_ok=True)
    if "," in image_base64 and image_base64.strip().startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]
    suffix = Path(filename or "").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=RUNTIME_UPLOADS) as handle:
        handle.write(base64.b64decode(image_base64))
        return Path(handle.name)


def dumps_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
