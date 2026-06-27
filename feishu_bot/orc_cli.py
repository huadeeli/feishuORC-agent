from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import BotConfig


class OrcCliError(RuntimeError):
    pass


def build_recognize_command(config: BotConfig, image_path: Path) -> list[str]:
    base = build_cli_base(config)
    return [
        *base,
        "recognize",
        str(image_path),
        "--ocr",
        config.ocr_mode,
        "--template",
        config.template_id,
        "--json",
    ]


def build_cli_base(config: BotConfig) -> list[str]:
    cli_path = config.cli_path
    if cli_path.suffix.lower() == ".py":
        return [config.python_executable, str(cli_path)]
    return [str(cli_path)]


def run_recognize(config: BotConfig, image_path: Path) -> dict[str, Any]:
    if config.ocr_service_url:
        return _post_json(
            f"{config.ocr_service_url}/api/v1/recognize",
            {
                "image_path": str(image_path),
                "filename": image_path.name,
                "ocr": config.ocr_mode,
                "template_id": config.template_id,
            },
            timeout=config.command_timeout,
        )
    command = build_recognize_command(config, image_path)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=config.project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.command_timeout,
        check=False,
        **_subprocess_startup_kwargs(),
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise OrcCliError(f"ORC CLI exited with {completed.returncode}: {details}")
    return parse_json_output(completed.stdout)


def run_calculate(config: BotConfig, values: dict[str, str]) -> dict[str, Any]:
    if config.ocr_service_url:
        return _post_json(
            f"{config.ocr_service_url}/api/v1/calculate",
            {"values": values},
            timeout=config.command_timeout,
        )
    command = [*build_cli_base(config), "calculate"]
    command.extend(f"{key}={value}" for key, value in values.items())
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        command,
        cwd=config.project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=config.command_timeout,
        check=False,
        **_subprocess_startup_kwargs(),
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "").strip()
        raise OrcCliError(f"ORC calculate exited with {completed.returncode}: {details}")
    return parse_json_output(completed.stdout)


def parse_json_output(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise OrcCliError("ORC CLI returned empty output.")
    start = text.find("{")
    if start > 0:
        text = text[start:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OrcCliError(f"ORC CLI returned non-JSON output: {stdout[:500]}") from exc
    if not isinstance(parsed, dict):
        raise OrcCliError("ORC CLI JSON output must be an object.")
    return parsed


def _post_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            error = json.loads(raw).get("error")
        except Exception:
            error = raw
        raise OrcCliError(f"OCR service HTTP {exc.code}: {error or exc.reason}") from exc
    except URLError as exc:
        raise OrcCliError(f"OCR service unavailable: {exc.reason}") from exc
    return parse_json_output(raw)


def _subprocess_startup_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startupinfo}
