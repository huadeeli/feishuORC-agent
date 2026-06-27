from __future__ import annotations

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .card_sessions import CardSession, CardSessionStore, extract_sent_message_id
from .config import BotConfig, ConfigError, ensure_runtime_dirs, load_config
from .feishu_client import FeishuApiClient
from .message_format import (
    BROKER_FEE_FIELD,
    FEE_FORM_ACTION,
    SERVICE_FEE_FIELD,
    build_calculation_card,
    build_fee_input_card,
    build_processing_card,
    build_recognition_card,
    format_calculation_reply,
    format_error_reply,
    format_recognition_reply,
    help_text,
    parse_message_content,
)
from .orc_cli import run_calculate, run_recognize


@dataclass(frozen=True)
class IncomingResource:
    chat_id: str
    message_id: str
    file_key: str
    resource_type: str
    filename: str
    note_text: str = ""


@dataclass(frozen=True)
class IncomingText:
    chat_id: str
    message_id: str
    text: str


class FeishuBotService:
    def __init__(self, config: BotConfig, api_client: FeishuApiClient | None = None) -> None:
        self.config = config
        self.api_client = api_client or FeishuApiClient(config)
        self.session_store = CardSessionStore(config.runtime_dir / "card_sessions")
        self.executor = ThreadPoolExecutor(max_workers=config.max_workers, thread_name_prefix="orc-feishu")

    def handle_event(self, data: Any, *, lark_module: Any | None = None) -> None:
        try:
            payload = event_to_dict(data, lark_module=lark_module)
            summary = summarize_message(payload)
            logging.info("received Feishu message: %s", summary)
            print(f"[ORC Feishu] received message: {summary}", flush=True)

            incoming_text = extract_incoming_text(payload)
            if incoming_text is not None:
                self._process_text(incoming_text)
                return

            incoming = extract_incoming_resource(payload)
            if incoming is None:
                chat_id = extract_chat_id(payload)
                if chat_id:
                    self.api_client.send_text(chat_id, self.config.unsupported_text)
                return

            if self.config.image_workflow == "form" and self.config.reply_style == "card":
                print("[ORC Feishu] image accepted, fee form task queued", flush=True)
                self.executor.submit(self._prepare_resource_form, incoming)
                return

            self.api_client.send_text(incoming.chat_id, self.config.ack_text)
            print("[ORC Feishu] image accepted, OCR task queued", flush=True)
            self.executor.submit(self._process_resource, incoming)
        except Exception as exc:
            logging.exception("failed to handle Feishu event")
            print(f"[ORC Feishu] event handling failed: {exc}", flush=True)

    def _process_text(self, incoming: IncomingText) -> None:
        try:
            values = parse_calculation_text(incoming.text)
            if values:
                result = run_calculate(self.config, values)
                self._send_result(
                    incoming.chat_id,
                    format_calculation_reply(result),
                    build_calculation_card(result),
                )
                return
            self.api_client.send_text(incoming.chat_id, help_text())
        except Exception as exc:
            logging.exception("failed to process Feishu text message")
            self.api_client.send_text(incoming.chat_id, format_error_reply(exc))

    def _process_resource(self, incoming: IncomingResource) -> None:
        try:
            started = time.monotonic()
            image_path = self.config.downloads_dir / incoming.filename
            print(f"[ORC Feishu] downloading image resource: {incoming.file_key}", flush=True)
            self.api_client.download_message_resource(
                message_id=incoming.message_id,
                file_key=incoming.file_key,
                resource_type=incoming.resource_type,
                destination=image_path,
            )
            result = run_recognize(self.config, image_path)
            _log_recognition_summary(result, image_path, started)
            result = apply_text_overrides(self.config, result, incoming.note_text)
            self._send_result(
                incoming.chat_id,
                format_recognition_reply(result),
                build_recognition_card(result),
            )
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            logging.exception("failed to process Feishu image message")
            self.api_client.send_text(incoming.chat_id, format_error_reply(exc))

    def _prepare_resource_form(self, incoming: IncomingResource) -> None:
        try:
            image_path = self.config.downloads_dir / incoming.filename
            print(f"[ORC Feishu] downloading image for fee form: {incoming.file_key}", flush=True)
            self.api_client.download_message_resource(
                message_id=incoming.message_id,
                file_key=incoming.file_key,
                resource_type=incoming.resource_type,
                destination=image_path,
            )
            session = self.session_store.create(
                chat_id=incoming.chat_id,
                source_message_id=incoming.message_id,
                image_path=image_path,
                note_text=incoming.note_text,
            )
            defaults = parse_labeled_values(incoming.note_text)
            response = self.api_client.send_interactive_card(
                incoming.chat_id,
                build_fee_input_card(
                    session_id=session.session_id,
                    defaults=defaults,
                    note_text=incoming.note_text,
                ),
            )
            card_message_id = extract_sent_message_id(response)
            if card_message_id:
                self.session_store.with_card_message_id(session, card_message_id)
            print(f"[ORC Feishu] fee form sent: session_id={session.session_id}", flush=True)
        except Exception:
            logging.exception("failed to prepare fee form; falling back to auto recognition")
            self.api_client.send_text(incoming.chat_id, self.config.ack_text)
            self._process_resource(incoming)

    def handle_card_action(self, data: Any, *, lark_module: Any | None = None) -> dict[str, Any]:
        try:
            payload = event_to_dict(data, lark_module=lark_module)
            return self._handle_card_action_payload(payload)
        except Exception as exc:
            logging.exception("failed to handle Feishu card action")
            return _callback_toast("error", f"卡片操作失败：{exc}")

    def _handle_card_action_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = extract_card_action(payload)
        action_value = _dict_value(action, "value")
        action_type = str(action_value.get("action") or "")
        session_id = str(action_value.get("session_id") or "")
        if action_type != FEE_FORM_ACTION or not session_id:
            return _callback_toast("warning", "未识别的卡片操作。")

        form_values = _dict_value(action, "form_value")
        try:
            service_fee = _normalize_fee_input(_form_value(form_values, SERVICE_FEE_FIELD))
            broker_fee = _normalize_fee_input(_form_value(form_values, BROKER_FEE_FIELD))
            session = self.session_store.load(session_id)
            callback_message_id = extract_card_message_id(payload)
            if callback_message_id and not session.card_message_id:
                session = self.session_store.with_card_message_id(session, callback_message_id)
        except KeyError:
            return _callback_toast("error", "这张卡片的图片记录已失效，请重新发送图片。")
        except ValueError as exc:
            return _callback_toast("error", str(exc))

        self.executor.submit(self._process_form_session, session, service_fee, broker_fee)
        return _callback_toast("info", "已开始识别并计算，请稍等。")

    def _process_form_session(self, session: CardSession, service_fee: str, broker_fee: str) -> None:
        try:
            started = time.monotonic()
            if session.card_message_id:
                self._try_update_card(session.card_message_id, build_processing_card())
            result = run_recognize(self.config, Path(session.image_path))
            _log_recognition_summary(result, Path(session.image_path), started)
            result = apply_text_overrides(self.config, result, session.note_text)
            result = apply_text_overrides(self.config, result, f"手续费{service_fee} 中介费{broker_fee}")
            text = format_recognition_reply(result)
            card = build_recognition_card(result)
            if session.card_message_id:
                try:
                    self.api_client.update_interactive_card(session.card_message_id, card)
                    return
                except Exception:
                    logging.exception("failed to update Feishu result card; falling back to new message")
            self._send_result(session.chat_id, text, card)
        except Exception as exc:  # pragma: no cover - defensive runtime logging
            logging.exception("failed to process fee form session")
            self.api_client.send_text(session.chat_id, format_error_reply(exc))

    def _try_update_card(self, message_id: str, card: dict[str, Any]) -> None:
        try:
            self.api_client.update_interactive_card(message_id, card)
        except Exception:
            logging.exception("failed to update Feishu card")

    def _send_result(self, chat_id: str, text: str, card: dict[str, Any]) -> None:
        if self.config.reply_style == "card":
            try:
                self.api_client.send_interactive_card(chat_id, card)
                return
            except Exception:
                logging.exception("failed to send Feishu card; falling back to text")
        self.api_client.send_text(chat_id, text)


def event_to_dict(data: Any, *, lark_module: Any | None = None) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if lark_module is not None:
        raw = lark_module.JSON.marshal(data)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"Unsupported Feishu event payload: {type(data)!r}")


def extract_chat_id(payload: dict[str, Any]) -> str:
    message = _message(payload)
    return str(_get_value(message, "chat_id") or "")


def extract_incoming_resource(payload: dict[str, Any]) -> IncomingResource | None:
    message = _message(payload)
    message_id = str(_get_value(message, "message_id") or "")
    chat_id = str(_get_value(message, "chat_id") or "")
    message_type = str(_get_value(message, "message_type") or "")
    content = parse_message_content(_get_value(message, "content"))

    image_key = str(content.get("image_key") or "")
    file_key = str(content.get("file_key") or "")
    if message_type == "post":
        image_key = image_key or extract_post_image_key(content)
        note_text = extract_post_text(content)
        if image_key:
            return IncomingResource(
                chat_id=chat_id,
                message_id=message_id,
                file_key=image_key,
                resource_type="image",
                filename=_safe_filename(content.get("file_name") or f"{message_id}.jpg"),
                note_text=note_text,
            )

    if image_key:
        return IncomingResource(
            chat_id=chat_id,
            message_id=message_id,
            file_key=image_key,
            resource_type="image",
            filename=_safe_filename(content.get("file_name") or f"{message_id}.jpg"),
            note_text="",
        )
    if message_type == "file" and file_key:
        return IncomingResource(
            chat_id=chat_id,
            message_id=message_id,
            file_key=file_key,
            resource_type="file",
            filename=_safe_filename(content.get("file_name") or f"{message_id}.jpg"),
            note_text="",
        )
    return None


def extract_incoming_text(payload: dict[str, Any]) -> IncomingText | None:
    message = _message(payload)
    message_type = str(_get_value(message, "message_type") or "")
    if message_type != "text":
        if message_type == "post":
            content = parse_message_content(_get_value(message, "content"))
            post_text = extract_post_text(content)
            if post_text and not extract_post_image_key(content):
                return IncomingText(
                    chat_id=str(_get_value(message, "chat_id") or ""),
                    message_id=str(_get_value(message, "message_id") or ""),
                    text=post_text,
                )
        return None
    content = parse_message_content(_get_value(message, "content"))
    text = str(content.get("text") or "").strip()
    return IncomingText(
        chat_id=str(_get_value(message, "chat_id") or ""),
        message_id=str(_get_value(message, "message_id") or ""),
        text=text,
    )


FIELD_ALIASES = {
    "gross_weight": ("毛重", "毛"),
    "tare_weight": ("皮重", "皮"),
    "unit_price": ("单价", "价格"),
    "settlement_weight": ("结算重量", "结算重", "结算"),
    "tax_fee": ("税费", "税款", "税"),
    "service_fee_per_ton": ("手续费", "客户手续费"),
    "broker_fee_per_ton": ("中介费", "客户中介费"),
}


def parse_calculation_text(text: str) -> dict[str, str]:
    values = parse_labeled_values(text)
    required = {"gross_weight", "tare_weight", "unit_price", "settlement_weight", "tax_fee"}
    if not required.issubset(values):
        return {}
    values.setdefault("service_fee_per_ton", "0")
    values.setdefault("broker_fee_per_ton", "0")
    return values


def parse_labeled_values(text: str) -> dict[str, str]:
    normalized = text.replace("：", ":").replace("，", " ").replace(",", " ")
    values: dict[str, str] = {}
    for key, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            pattern = rf"{re.escape(alias)}\s*[:=]?\s*(-?\d+(?:\.\d+)?)"
            match = re.search(pattern, normalized)
            if match:
                values[key] = match.group(1)
                break
    return values


def apply_text_overrides(config: BotConfig, result: dict[str, Any], note_text: str) -> dict[str, Any]:
    overrides = parse_labeled_values(note_text)
    if not overrides:
        return result
    calculation = result.get("calculation", {})
    inputs = calculation.get("inputs", {})
    if not isinstance(inputs, dict):
        return result
    values = {str(key): str(value or "") for key, value in inputs.items()}
    values.update(overrides)
    recalculated = run_calculate(config, values)
    result["calculation"] = recalculated
    warnings = result.setdefault("warnings", [])
    if isinstance(warnings, list):
        used = "，".join(f"{key}={value}" for key, value in overrides.items())
        warnings.append(f"已使用随图文字修正计算: {used}")
    return result


def extract_post_image_key(content: dict[str, Any]) -> str:
    for item in _walk_post_items(content.get("content")):
        if str(item.get("tag") or "") == "img":
            image_key = str(item.get("image_key") or "")
            if image_key:
                return image_key
    return ""


def extract_post_text(content: dict[str, Any]) -> str:
    parts: list[str] = []
    title = str(content.get("title") or "").strip()
    if title:
        parts.append(title)
    for item in _walk_post_items(content.get("content")):
        if str(item.get("tag") or "") == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _walk_post_items(node: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if isinstance(node, dict):
        items.append(node)
        return items
    if isinstance(node, list):
        for child in node:
            items.extend(_walk_post_items(child))
    return items


def summarize_message(payload: dict[str, Any]) -> dict[str, str]:
    message = _message(payload)
    content = parse_message_content(_get_value(message, "content"))
    return {
        "message_id": str(_get_value(message, "message_id") or ""),
        "chat_id": str(_get_value(message, "chat_id") or ""),
        "message_type": str(_get_value(message, "message_type") or ""),
        "content_keys": ",".join(sorted(content.keys())),
    }


def _message(payload: dict[str, Any]) -> Any:
    event = payload.get("event")
    if isinstance(event, dict):
        return event.get("message", {})
    return _get_value(event, "message") or {}


def _get_value(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def extract_card_action(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event")
    action = _get_value(event, "action") or {}
    return action if isinstance(action, dict) else vars(action)


def extract_card_message_id(payload: dict[str, Any]) -> str:
    event = payload.get("event")
    context = _get_value(event, "context") or {}
    return str(_get_value(context, "open_message_id") or "")


def _dict_value(mapping: Any, key: str) -> dict[str, Any]:
    value = _get_value(mapping, key)
    return value if isinstance(value, dict) else {}


def _form_value(form_values: dict[str, Any], key: str) -> str:
    value = form_values.get(key, "")
    if isinstance(value, dict):
        for candidate in ("value", "input_value", "text"):
            if candidate in value:
                return str(value.get(candidate) or "")
        return ""
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value or "")


def _normalize_fee_input(value: str) -> str:
    text = str(value or "").strip()
    text = text.replace("元/吨", "").replace("元", "").replace("/吨", "").replace("吨", "").strip()
    if not text:
        return "0"
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ValueError("手续费和中介费请输入非负数字，例如 15 或 3。")
    return text


def _callback_toast(level: str, content: str) -> dict[str, Any]:
    return {"toast": {"type": level, "content": content}}


def run_bot(config: BotConfig) -> None:
    ensure_runtime_dirs(config)
    py_log_level = getattr(logging, config.log_level, logging.INFO)
    handler = RotatingFileHandler(
        config.log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(py_log_level)
    for logger_name in ("lark", "lark_oapi", "websockets", "websockets.client"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    except ImportError as exc:  # pragma: no cover - depends on optional package
        raise SystemExit("Missing dependency lark-oapi. Run: python -m pip install -r requirements-feishu.txt") from exc

    service = FeishuBotService(config)

    def do_p2_im_message_receive_v1(data: Any) -> None:
        service.handle_event(data, lark_module=lark)

    def do_p2_card_action_trigger(data: Any) -> Any:
        return P2CardActionTriggerResponse(service.handle_card_action(data, lark_module=lark))

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .register_p2_card_action_trigger(do_p2_card_action_trigger)
        .build()
    )
    kwargs: dict[str, Any] = {"event_handler": event_handler}
    if hasattr(lark, "LogLevel"):
        kwargs["log_level"] = _lark_log_level(lark, config.sdk_log_level)
    client = lark.ws.Client(config.app_id, config.app_secret, **kwargs)
    logging.info(
        "starting Feishu long-connection bot, log_level=%s, sdk_log_level=%s, "
        "ocr_mode=%s, reply_style=%s, image_workflow=%s",
        config.log_level,
        config.sdk_log_level,
        config.ocr_mode,
        config.reply_style,
        config.image_workflow,
    )
    print(
        "[ORC Feishu] bot starting; waiting for im.message.receive_v1 events. "
        f"ocr_mode={config.ocr_mode}, reply_style={config.reply_style}, image_workflow={config.image_workflow}. "
        "Send text '123' or a waste-paper screenshot in Feishu.",
        flush=True,
    )
    client.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="废纸 ORC 飞书原生长连接机器人")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--check-config", action="store_true", help="只检查本地配置，不连接飞书")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.env_file, require_credentials=not args.check_config)
        if args.check_config:
            ensure_runtime_dirs(config)
            print(json.dumps(config_summary(config), ensure_ascii=False, indent=2))
            return 0
        run_bot(config)
        return 0
    except ConfigError as exc:
        print(f"配置错误: {exc}")
        return 2


def config_summary(config: BotConfig) -> dict[str, Any]:
    return {
        "project_root": str(config.project_root),
        "cli_path": str(config.cli_path),
        "ocr_service_url": config.ocr_service_url,
        "ocr_mode": config.ocr_mode,
        "template_id": config.template_id,
        "runtime_dir": str(config.runtime_dir),
        "downloads_dir": str(config.downloads_dir),
        "log_file": str(config.log_file),
        "log_level": config.log_level,
        "sdk_log_level": config.sdk_log_level,
        "reply_style": config.reply_style,
        "image_workflow": config.image_workflow,
        "has_feishu_app_id": bool(config.app_id),
        "has_feishu_app_secret": bool(config.app_secret),
    }


def _lark_log_level(lark: Any, name: str) -> Any:
    normalized = "WARNING" if name.upper() == "WARN" else name.upper()
    level = getattr(lark.LogLevel, normalized, None)
    if level is not None:
        return level
    return getattr(lark.LogLevel, "WARNING", lark.LogLevel.ERROR)


def _log_recognition_summary(result: dict[str, Any], image_path: Path, started: float) -> None:
    ocr = result.get("ocr", {})
    logging.info(
        "recognition complete image=%s requested=%s selected=%s model=%s fallback=%s "
        "ocr_elapsed_ms=%s total_elapsed_ms=%s attempts=%s",
        image_path.name,
        ocr.get("requested_mode"),
        ocr.get("selected_mode"),
        ocr.get("model"),
        ocr.get("fallback_used"),
        ocr.get("total_elapsed_ms"),
        round((time.monotonic() - started) * 1000),
        ocr.get("attempts"),
    )


def _safe_filename(value: Any) -> str:
    name = str(value or "feishu-image.jpg")
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    return name or "feishu-image.jpg"


if __name__ == "__main__":
    raise SystemExit(main())
