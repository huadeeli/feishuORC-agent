from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = application_root()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotConfig:
    app_id: str
    app_secret: str
    ocr_mode: str
    template_id: str
    cli_path: Path
    python_executable: str
    project_root: Path
    runtime_dir: Path
    downloads_dir: Path
    log_file: Path
    command_timeout: int
    max_workers: int
    feishu_base_url: str
    log_level: str
    reply_style: str
    image_workflow: str
    ack_text: str
    unsupported_text: str
    ocr_service_url: str = ""
    sdk_log_level: str = "WARNING"


def load_config(env_file: Path | None = None, *, require_credentials: bool = True) -> BotConfig:
    env_file = env_file or PROJECT_ROOT / ".env"
    load_env_file(env_file)

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if require_credentials and (not app_id or not app_secret):
        raise ConfigError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env or environment variables.")

    runtime_dir = _resolve_path(os.getenv("ORC_FEISHU_RUNTIME_DIR", "runtime/feishu"))
    downloads_dir = runtime_dir / "downloads"
    log_file = runtime_dir / "logs" / "feishu_bot.log"

    default_cli_path = "orc-calc-cli.exe" if getattr(sys, "frozen", False) else "orc-calc.py"

    return BotConfig(
        app_id=app_id,
        app_secret=app_secret,
        ocr_mode=os.getenv("ORC_OCR_MODE", "auto").strip() or "auto",
        template_id=os.getenv("ORC_TEMPLATE_ID", "auto").strip() or "auto",
        cli_path=_resolve_path(os.getenv("ORC_CLI_PATH", default_cli_path)),
        ocr_service_url=os.getenv("ORC_OCR_SERVICE_URL", "").strip().rstrip("/"),
        python_executable=os.getenv("ORC_PYTHON", sys.executable).strip() or sys.executable,
        project_root=PROJECT_ROOT,
        runtime_dir=runtime_dir,
        downloads_dir=downloads_dir,
        log_file=log_file,
        command_timeout=_read_int("ORC_COMMAND_TIMEOUT", 900),
        max_workers=_read_int("ORC_FEISHU_MAX_WORKERS", 2),
        feishu_base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn").rstrip("/"),
        log_level=os.getenv("ORC_FEISHU_LOG_LEVEL", "INFO").strip().upper() or "INFO",
        reply_style=_read_choice("ORC_FEISHU_REPLY_STYLE", "card", {"card", "text"}),
        image_workflow=_read_choice("ORC_FEISHU_IMAGE_WORKFLOW", "auto", {"auto", "form"}),
        ack_text=os.getenv("ORC_FEISHU_ACK_TEXT", "收到图片，正在识别废纸结算数据，请稍等。"),
        unsupported_text=os.getenv("ORC_FEISHU_UNSUPPORTED_TEXT", "请发送废纸结算截图，我会自动识别并回复计算结果。"),
        sdk_log_level=os.getenv("ORC_FEISHU_SDK_LOG_LEVEL", "WARNING").strip().upper() or "WARNING",
    )


def ensure_runtime_dirs(config: BotConfig) -> None:
    config.downloads_dir.mkdir(parents=True, exist_ok=True)
    (config.runtime_dir / "card_sessions").mkdir(parents=True, exist_ok=True)
    config.log_file.parent.mkdir(parents=True, exist_ok=True)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_path(value: str) -> Path:
    path = Path(value.strip())
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _read_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower() or default
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ConfigError(f"{name} must be one of: {allowed}.")
    return value
