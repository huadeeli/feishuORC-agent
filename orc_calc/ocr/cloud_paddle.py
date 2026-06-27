from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from orc_calc.core.recognizer import OCRLine

from .base import OCRProvider, OCRProviderResult


DEFAULT_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
DEFAULT_MODEL = "PP-OCRv5"
DEFAULT_OPTIONAL_PAYLOAD = {
    "useDocOrientationClassify": False,
    "useDocUnwarping": False,
    "useTextlineOrientation": False,
}


class CloudPaddleOCRProvider(OCRProvider):
    name = "cloud-paddleocr-official"

    def __init__(
        self,
        endpoint: str | None = None,
        token: str | None = None,
        model: str | None = None,
        *,
        request_timeout: int | None = None,
        poll_interval: float | None = None,
        max_wait: int | None = None,
    ) -> None:
        self.endpoint = (endpoint if endpoint is not None else os.getenv("PADDLEOCR_API_URL") or DEFAULT_JOB_URL).rstrip("/")
        self.token = token if token is not None else os.getenv("PADDLEOCR_ACCESS_TOKEN", "")
        self.model = model if model is not None else os.getenv("PADDLEOCR_CLOUD_MODEL", DEFAULT_MODEL)
        self.request_timeout = int(request_timeout or os.getenv("PADDLEOCR_CLOUD_REQUEST_TIMEOUT", "60"))
        self.poll_interval = float(poll_interval or os.getenv("PADDLEOCR_CLOUD_POLL_INTERVAL", "3"))
        self.max_wait = int(max_wait or os.getenv("PADDLEOCR_CLOUD_MAX_WAIT", "300"))

    def recognize(self, image_path: str | Path, *, image_filename: str | None = None) -> OCRProviderResult:
        path = Path(image_path)
        missing = self._missing_configuration()
        if missing:
            return OCRProviderResult(
                self.name,
                [],
                [missing],
                {"model": self.model, "mode": "cloud", "configured": False},
            )

        try:
            lines = self._recognize_lines(path, image_filename=image_filename)
        except Exception as exc:
            return OCRProviderResult(
                self.name,
                [],
                [f"云端 OCR 调用失败: {_friendly_cloud_error(exc)}"],
                {"model": self.model, "mode": "cloud", "configured": True},
            )

        warnings = []
        if not lines:
            warnings.append("云端 OCR 已完成，但没有解析到可用文字；可能需要调整官方 API 返回结果解析。")
        return OCRProviderResult(
            self.name,
            lines,
            warnings,
            {"model": self.model, "mode": "cloud", "configured": True},
        )

    def status(self) -> dict[str, Any]:
        missing = self._missing_configuration()
        return {
            "cloud_ready": not bool(missing),
            "cloud_configured": not bool(missing),
            "cloud_protocol": "official-async-api",
            "cloud_endpoint": self.endpoint,
            "cloud_model": self.model,
            "cloud_live_checked": False,
            "last_cloud_error": missing or "",
        }

    def check(self, image_path: str | Path | None = None) -> dict[str, Any]:
        status = self.status()
        if image_path is None or not status["cloud_configured"]:
            return status

        path = Path(image_path)
        try:
            lines = self._recognize_lines(path, image_filename=path.name)
            return {
                **status,
                "cloud_ready": True,
                "cloud_live_checked": True,
                "cloud_result_line_count": len(lines),
                "last_cloud_error": "",
            }
        except Exception as exc:
            return {
                **status,
                "cloud_ready": False,
                "cloud_live_checked": True,
                "cloud_result_line_count": 0,
                "last_cloud_error": _friendly_cloud_error(exc),
            }

    def _missing_configuration(self) -> str:
        if not self.endpoint:
            return "未配置 PADDLEOCR_API_URL。"
        if not self.token:
            return "未配置 PADDLEOCR_ACCESS_TOKEN；云端 OCR 不会被调用。"
        return ""

    def _recognize_lines(self, path: Path, *, image_filename: str | None = None) -> list[OCRLine]:
        if not path.exists():
            raise FileNotFoundError(str(path))
        requests = _load_requests()
        headers = {"Authorization": f"bearer {self.token}"}
        job_id = self._submit_job(requests, headers, path, image_filename=image_filename)
        done_payload = self._poll_job(requests, headers, job_id)
        json_url = _get_nested(done_payload, "resultUrl", "jsonUrl")
        if not json_url:
            raise RuntimeError("云端 OCR 任务完成，但响应中没有 data.resultUrl.jsonUrl。")
        jsonl_text = self._download_jsonl(requests, headers, str(json_url))
        return _parse_official_jsonl(jsonl_text)

    def _submit_job(self, requests: Any, headers: dict[str, str], path: Path, *, image_filename: str | None) -> str:
        data = {
            "model": self.model,
            "optionalPayload": json.dumps(DEFAULT_OPTIONAL_PAYLOAD, ensure_ascii=False),
        }
        with path.open("rb") as handle:
            files = {"file": (image_filename or path.name, handle)}
            response = requests.post(
                self.endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=self.request_timeout,
            )
        payload = _json_response(response, "提交云端 OCR 任务失败")
        job_id = _get_nested(payload, "data", "jobId")
        if not job_id:
            raise RuntimeError("提交云端 OCR 任务成功，但响应中没有 data.jobId。")
        return str(job_id)

    def _poll_job(self, requests: Any, headers: dict[str, str], job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.max_wait
        job_url = f"{self.endpoint}/{job_id}"
        last_state = ""
        while time.monotonic() < deadline:
            response = requests.get(job_url, headers=headers, timeout=self.request_timeout)
            payload = _json_response(response, "查询云端 OCR 任务失败")
            data = payload.get("data") if isinstance(payload, dict) else {}
            if not isinstance(data, dict):
                raise RuntimeError("查询云端 OCR 任务失败：响应中没有 data 对象。")
            state = str(data.get("state") or "")
            last_state = state or last_state
            if state == "done":
                return data
            if state == "failed":
                raise RuntimeError(str(data.get("errorMsg") or "云端 OCR 任务失败。"))
            if state not in {"pending", "running"}:
                raise RuntimeError(f"云端 OCR 返回未知任务状态：{state}")
            time.sleep(self.poll_interval)
        raise RuntimeError(f"云端 OCR 等待超时：{self.max_wait} 秒，最后状态：{last_state or 'unknown'}。")

    def _download_jsonl(self, requests: Any, headers: dict[str, str], json_url: str) -> str:
        response = requests.get(json_url, headers=headers, timeout=self.request_timeout)
        if response.status_code != 200:
            response = requests.get(json_url, timeout=self.request_timeout)
        if response.status_code != 200:
            raise RuntimeError(f"下载云端 OCR JSONL 失败：HTTP {response.status_code} {response.text[:400]}")
        return response.text


def cloud_runtime_status() -> dict[str, Any]:
    return CloudPaddleOCRProvider().status()


def check_cloud_ocr(image_path: str | Path | None = None) -> dict[str, Any]:
    return CloudPaddleOCRProvider().check(image_path)


def _load_requests() -> Any:
    try:
        import requests  # type: ignore

        return requests
    except Exception as exc:
        raise RuntimeError("云端 OCR 需要 requests，请先安装 requests>=2.31。") from exc


def _json_response(response: Any, context: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{context}：HTTP {response.status_code} {str(response.text)[:500]}")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError(f"{context}：响应不是 JSON。") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{context}：响应 JSON 不是对象。")
    return payload


def _parse_official_jsonl(text: str) -> list[OCRLine]:
    lines: list[OCRLine] = []
    for raw_line in text.strip().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        payload = json.loads(raw_line)
        result = payload.get("result", payload) if isinstance(payload, dict) else payload
        lines.extend(_parse_cloud_response(result))
    return _dedupe_lines(lines)


def _parse_cloud_response(data: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []
    _collect_lines(data, lines)
    return _dedupe_lines(lines)


def _collect_lines(node: Any, lines: list[OCRLine]) -> None:
    if isinstance(node, dict):
        if _collect_rec_texts(node, lines):
            return
        text = node.get("text") or node.get("words") or node.get("rec_text") or node.get("recText")
        if text:
            score = node.get("confidence") or node.get("score") or node.get("rec_score") or node.get("recScore") or 0.0
            box = node.get("box") or node.get("bbox") or node.get("poly") or node.get("dt_polys") or node.get("dtPolys")
            lines.append(OCRLine(str(text), _safe_float(score), _normalize_box(box)))
            return
        for value in node.values():
            if isinstance(value, (dict, list, tuple)):
                _collect_lines(value, lines)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _collect_lines(item, lines)


def _collect_rec_texts(node: dict[str, Any], lines: list[OCRLine]) -> bool:
    rec_texts = _first_list(node, "rec_texts", "recTexts", "texts")
    if not rec_texts:
        return False
    rec_scores = _first_list(node, "rec_scores", "recScores", "scores") or []
    rec_boxes = _first_list(node, "rec_boxes", "recBoxes", "rec_polys", "recPolys", "dt_polys", "dtPolys") or []
    for index, text in enumerate(rec_texts):
        if not text:
            continue
        score = rec_scores[index] if index < len(rec_scores) else 0.0
        box = rec_boxes[index] if index < len(rec_boxes) else None
        lines.append(OCRLine(str(text), _safe_float(score), _normalize_box(box)))
    return True


def _first_list(node: dict[str, Any], *keys: str) -> list[Any] | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, list):
            return value
    return None


def _dedupe_lines(lines: list[OCRLine]) -> list[OCRLine]:
    unique: list[OCRLine] = []
    seen: set[tuple[str, str]] = set()
    for line in lines:
        key = (line.text, json.dumps(line.box, ensure_ascii=False, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _normalize_box(box: Any) -> Any:
    if hasattr(box, "tolist"):
        return box.tolist()
    return box


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _get_nested(node: Any, *keys: str) -> Any:
    current = node
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _friendly_cloud_error(exc: Exception) -> str:
    message = str(exc).strip()
    if "401" in message or "403" in message:
        return f"云端认证失败，请检查 PADDLEOCR_ACCESS_TOKEN 是否正确或已过期。{message}"
    if "429" in message:
        return f"云端额度或频率受限。{message}"
    return message
