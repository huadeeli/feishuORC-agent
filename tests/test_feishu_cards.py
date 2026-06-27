from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_bot.card_sessions import CardSessionStore
from feishu_bot.config import BotConfig, ConfigError, load_config
from feishu_bot.feishu_client import FeishuApiClient
from feishu_bot.main import FeishuBotService, _normalize_fee_input
from feishu_bot.message_format import (
    BROKER_FEE_FIELD,
    FEE_FORM_ACTION,
    SERVICE_FEE_FIELD,
    build_calculation_card,
    build_fee_input_card,
    build_recognition_card,
    format_calculation_reply,
    format_recognition_reply,
)


def _config(reply_style: str = "card") -> BotConfig:
    root = Path(tempfile.gettempdir()) / "orc-feishu-test"
    return BotConfig(
        app_id="",
        app_secret="",
        ocr_mode="local",
        template_id="auto",
        cli_path=root / "orc-calc.py",
        python_executable="python",
        project_root=root,
        runtime_dir=root / "runtime" / "feishu",
        downloads_dir=root / "runtime" / "feishu" / "downloads",
        log_file=root / "runtime" / "feishu" / "logs" / "feishu_bot.log",
        command_timeout=900,
        max_workers=2,
        feishu_base_url="https://open.feishu.cn",
        log_level="DEBUG",
        reply_style=reply_style,
        image_workflow="auto",
        ack_text="ack",
        unsupported_text="unsupported",
    )


def _recognition_result() -> dict[str, object]:
    return {
        "fields": [
            {"label": "毛重", "value": "45.47"},
            {"label": "皮重", "value": "15.16"},
            {"label": "单价", "value": "1870"},
            {"label": "结算重量", "value": "28.4"},
            {"label": "税费", "value": "841.31"},
        ],
        "calculation": {
            "inputs": {
                "service_fee_per_ton": "15",
                "broker_fee_per_ton": "3",
            },
            "results": {
                "scale_weight": "30.31",
                "factory_amount": "52266.69",
                "customer_amount": "51812.04",
                "customer_service_fee": "454.65",
                "customer_broker_fee": "90.93",
            },
        },
        "ocr_lines": [
            {"text": "供应商 徐亮亮"},
            {"text": "送货日期* 20260604"},
            {"text": "车牌号 粤BKZ552"},
            {"text": "结算金额 52266.69"},
        ],
        "warnings": ["已使用随图文字修正计算: service_fee_per_ton=15，broker_fee_per_ton=3"],
    }


def _jianhui_new_result(*, image_amount_text: str = "结算金额 57488.08") -> dict[str, object]:
    return {
        "fields": [
            {"label": "毛重", "value": "50.06"},
            {"label": "皮重", "value": "14.63"},
            {"label": "单价", "value": "1730"},
            {"label": "结算重量", "value": "33.765"},
            {"label": "税费", "value": "925.37"},
        ],
        "calculation": {
            "inputs": {
                "service_fee_per_ton": "15",
                "broker_fee_per_ton": "3",
            },
            "results": {
                "scale_weight": "35.43",
                "factory_amount": "57488.08",
                "customer_amount": "56956.63",
                "customer_service_fee": "531.45",
                "customer_broker_fee": "106.29",
            },
        },
        "ocr_lines": [
            {"text": "发货单位 陈映莲"},
            {"text": "车牌号 粤AFN855"},
            {"text": "供货日期 2026-05-30"},
            {"text": "含税金额 58413.45"},
            {"text": image_amount_text},
        ],
        "warnings": [],
    }


class RecordingFeishuClient(FeishuApiClient):
    def __init__(self) -> None:
        super().__init__(_config())
        self.calls: list[dict[str, object]] = []

    def _request_json(self, method: str, path_with_query: str, payload: dict[str, object], *, auth: bool) -> dict[str, object]:
        self.calls.append({"method": method, "path": path_with_query, "payload": payload, "auth": auth})
        return {"code": 0}


class FakeApiClient:
    def __init__(self, *, fail_card: bool = False) -> None:
        self.fail_card = fail_card
        self.cards: list[dict[str, object]] = []
        self.texts: list[str] = []
        self.updates: list[dict[str, object]] = []

    def send_interactive_card(self, chat_id: str, card: dict[str, object]) -> dict[str, object]:
        self.cards.append({"chat_id": chat_id, "card": card})
        if self.fail_card:
            raise RuntimeError("card failed")
        return {"code": 0}

    def send_text(self, chat_id: str, text: str) -> dict[str, object]:
        self.texts.append(text)
        return {"code": 0}

    def update_interactive_card(self, message_id: str, card: dict[str, object]) -> dict[str, object]:
        self.updates.append({"message_id": message_id, "card": card})
        return {"code": 0}


class ImmediateExecutor:
    def submit(self, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        return fn(*args, **kwargs)


class FeishuCardTests(unittest.TestCase):
    def test_reply_style_config_defaults_to_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("", encoding="utf-8")
            config = load_config(env_file, require_credentials=False)

        self.assertEqual(config.reply_style, "card")

    def test_reply_style_config_accepts_text_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("ORC_FEISHU_REPLY_STYLE=text\n", encoding="utf-8")
            config = load_config(env_file, require_credentials=False)

        self.assertEqual(config.reply_style, "text")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("ORC_FEISHU_REPLY_STYLE=bad\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(env_file, require_credentials=False)

    def test_image_workflow_config_accepts_form_and_rejects_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("ORC_FEISHU_IMAGE_WORKFLOW=form\n", encoding="utf-8")
            config = load_config(env_file, require_credentials=False)

        self.assertEqual(config.image_workflow, "form")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            env_file = Path(tmp) / ".env"
            env_file.write_text("ORC_FEISHU_IMAGE_WORKFLOW=bad\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(env_file, require_credentials=False)

    def test_fee_input_card_contains_inputs_button_and_session(self) -> None:
        card = build_fee_input_card(
            session_id="sess_1",
            defaults={SERVICE_FEE_FIELD: "15", BROKER_FEE_FIELD: "3"},
            note_text="手续费15",
        )
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["header"]["title"]["content"], "废纸ORC待计算")
        self.assertIn('"tag": "form"', serialized)
        self.assertIn('"action_type": "form_submit"', serialized)
        self.assertIn('"name": "service_fee_per_ton"', serialized)
        self.assertIn('"name": "broker_fee_per_ton"', serialized)
        self.assertIn('"action": "orc_fee_form_calculate"', serialized)
        self.assertIn('"session_id": "sess_1"', serialized)
        self.assertIn("识别并计算", serialized)

    def test_normalize_fee_input_allows_blank_and_rejects_non_numeric_values(self) -> None:
        self.assertEqual(_normalize_fee_input(""), "0")
        self.assertEqual(_normalize_fee_input("15元"), "15")
        with self.assertRaises(ValueError):
            _normalize_fee_input("十五")

    def test_recognition_card_contains_title_amounts_details_and_warning(self) -> None:
        card = build_recognition_card(_recognition_result())
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["header"]["title"]["content"], "废纸ORC识别完成")
        self.assertIn("转客户钱：51812.04", serialized)
        self.assertIn("<font color='red'>**转客户钱：51812.04**</font>", serialized)
        self.assertIn("收厂钱：52266.69", serialized)
        self.assertIn("司磅重量：30.31", serialized)
        self.assertIn("供应商", serialized)
        self.assertIn("徐亮亮", serialized)
        self.assertIn("日期", serialized)
        self.assertIn("20260604", serialized)
        self.assertIn("车牌", serialized)
        self.assertIn("粤BKZ552", serialized)
        self.assertIn("毛重", serialized)
        self.assertIn("中介费", serialized)
        self.assertIn("客户手续费：30.31 × 15 = 454.65", serialized)
        self.assertIn("<font color='blue'>客户手续费：30.31 × 15 = 454.65</font>", serialized)
        self.assertIn("客户中介费：30.31 × 3 = 90.93", serialized)
        self.assertIn("<font color='blue'>客户中介费：30.31 × 3 = 90.93</font>", serialized)
        self.assertIn("转客户钱：52266.69 - 454.65 = 51812.04", serialized)
        self.assertIn("<font color='red'>**转客户钱：52266.69 - 454.65 = 51812.04**</font>", serialized)
        self.assertIn("收厂钱：1870 × 28.4 - 841.31 = 52266.69（验证一致）", serialized)
        self.assertIn("<font color='blue'>手续费\\n15</font>", serialized)
        self.assertIn("<font color='blue'>中介费\\n3</font>", serialized)
        self.assertIn("手续费=15", serialized)
        self.assertNotIn("service_fee_per_ton", serialized)

    def test_recognition_text_reply_contains_supplier_date_and_plate(self) -> None:
        reply = format_recognition_reply(_recognition_result())

        self.assertIn("供应商: 徐亮亮", reply)
        self.assertIn("日期: 20260604", reply)
        self.assertIn("车牌: 粤BKZ552", reply)
        self.assertIn("收厂钱验证: 验证一致", reply)

    def test_jianhui_new_labels_and_factory_amount_verification_pass(self) -> None:
        card = build_recognition_card(_jianhui_new_result())
        serialized = json.dumps(card, ensure_ascii=False)
        reply = format_recognition_reply(_jianhui_new_result())

        self.assertIn("陈映莲", serialized)
        self.assertIn("2026-05-30", serialized)
        self.assertIn("粤AFN855", serialized)
        self.assertIn("收厂钱：1730 × 33.765 - 925.37 = 57488.08（验证一致）", serialized)
        self.assertIn("供应商: 陈映莲", reply)
        self.assertIn("日期: 2026-05-30", reply)
        self.assertIn("车牌: 粤AFN855", reply)
        self.assertIn("收厂钱验证: 验证一致", reply)

    def test_jianhui_truncated_labels_use_next_line_values(self) -> None:
        result = _jianhui_new_result()
        result["ocr_lines"] = [
            {"text": "发货单..."},
            {"text": "陈映莲"},
            {"text": "供货日..."},
            {"text": "2026-05-30"},
            {"text": "车牌号 粤AFN855"},
            {"text": "结算金额 57488.08"},
        ]
        reply = format_recognition_reply(result)

        self.assertIn("供应商: 陈映莲", reply)
        self.assertIn("日期: 2026-05-30", reply)

    def test_factory_amount_verification_fails_when_image_amount_differs(self) -> None:
        card = build_recognition_card(_jianhui_new_result(image_amount_text="结算金额 57480.00"))
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertIn(
            "收厂钱：1730 × 33.765 - 925.37 = 57488.08（验证不通过，图片结算金额=57480.00）",
            serialized,
        )

    def test_factory_amount_verification_ignores_tax_included_amount(self) -> None:
        card = build_recognition_card(_jianhui_new_result(image_amount_text="备注 已完成"))
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertIn(
            "收厂钱：1730 × 33.765 - 925.37 = 57488.08（验证不通过，未识别到图片结算金额）",
            serialized,
        )
        self.assertNotIn("图片结算金额=58413.45", serialized)

    def test_recognition_card_tolerates_missing_fields(self) -> None:
        card = build_recognition_card({"fields": [], "calculation": {"results": {}}})
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertIn("废纸ORC识别完成", serialized)
        self.assertIn("转客户钱：-", serialized)

    def test_calculation_card_contains_key_amounts(self) -> None:
        result = {
            "inputs": {
                "gross_weight": "45.74",
                "tare_weight": "15.81",
                "unit_price": "1800",
                "settlement_weight": "29.5",
                "tax_fee": "800",
                "service_fee_per_ton": "15",
                "broker_fee_per_ton": "3",
            },
            "results": {
                "scale_weight": "29.93",
                "factory_amount": "52300.00",
                "customer_amount": "51851.05",
                "customer_service_fee": "448.95",
                "customer_broker_fee": "89.79",
            },
            "labels": {},
        }
        card = build_calculation_card(result)
        serialized = json.dumps(card, ensure_ascii=False)

        self.assertEqual(card["header"]["title"]["content"], "废纸ORC文字计算完成")
        self.assertIn("转客户钱：51851.05", serialized)
        self.assertIn("<font color='red'>**转客户钱：51851.05**</font>", serialized)
        self.assertIn("客户手续费：29.93 × 15 = 448.95", serialized)
        self.assertIn("<font color='blue'>客户手续费：29.93 × 15 = 448.95</font>", serialized)
        self.assertIn("客户中介费：29.93 × 3 = 89.79", serialized)
        self.assertIn("<font color='blue'>客户中介费：29.93 × 3 = 89.79</font>", serialized)
        self.assertIn("收厂钱：1800 × 29.5 - 800 = 52300.00", serialized)
        self.assertIn("转客户钱：52300.00 - 448.95 = 51851.05", serialized)
        self.assertIn("<font color='red'>**转客户钱：52300.00 - 448.95 = 51851.05**</font>", serialized)
        self.assertIn("客户中介费", serialized)

    def test_send_interactive_card_uses_interactive_message_type(self) -> None:
        client = RecordingFeishuClient()
        client.send_interactive_card("oc_1", {"config": {}, "elements": []})

        payload = client.calls[0]["payload"]
        self.assertEqual(payload["receive_id"], "oc_1")
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(json.loads(str(payload["content"])), {"config": {}, "elements": []})

    def test_update_interactive_card_uses_update_message_endpoint(self) -> None:
        client = RecordingFeishuClient()
        client.update_interactive_card("om_1", {"config": {}, "elements": []})

        call = client.calls[0]
        payload = call["payload"]
        self.assertEqual(call["method"], "PATCH")
        self.assertEqual(call["path"], "/open-apis/im/v1/messages/om_1")
        self.assertEqual(json.loads(str(payload["content"])), {"config": {}, "elements": []})

    def test_card_mode_falls_back_to_text_when_card_send_fails(self) -> None:
        api = FakeApiClient(fail_card=True)
        service = FeishuBotService(_config("card"), api_client=api)  # type: ignore[arg-type]
        text = format_calculation_reply({"inputs": {}, "results": {}, "labels": {}})

        with patch("logging.exception"):
            service._send_result("oc_1", text, {"config": {}, "elements": []})

        self.assertEqual(len(api.cards), 1)
        self.assertEqual(api.texts, [text])

    def test_text_mode_skips_card_send(self) -> None:
        api = FakeApiClient()
        service = FeishuBotService(_config("text"), api_client=api)  # type: ignore[arg-type]

        service._send_result("oc_1", "plain result", {"config": {}, "elements": []})

        self.assertEqual(api.cards, [])
        self.assertEqual(api.texts, ["plain result"])

    def test_card_action_uses_form_fees_and_updates_original_card(self) -> None:
        api = FakeApiClient()
        config = _config("card")
        service = FeishuBotService(config, api_client=api)  # type: ignore[arg-type]
        service.executor = ImmediateExecutor()  # type: ignore[assignment]
        store = CardSessionStore(config.runtime_dir / "card_sessions")
        session = store.create(
            chat_id="oc_1",
            source_message_id="om_source",
            image_path=config.downloads_dir / "image.jpg",
            note_text="",
        )
        session = store.with_card_message_id(session, "om_card")

        recognize_result = {
            "fields": [
                {"label": "毛重", "value": "45.74"},
                {"label": "皮重", "value": "15.81"},
                {"label": "单价", "value": "1800"},
                {"label": "结算重量", "value": "29.5"},
                {"label": "税费", "value": "800"},
            ],
            "calculation": {
                "inputs": {
                    "gross_weight": "45.74",
                    "tare_weight": "15.81",
                    "unit_price": "1800",
                    "settlement_weight": "29.5",
                    "tax_fee": "800",
                    "service_fee_per_ton": "0",
                    "broker_fee_per_ton": "0",
                },
                "results": {},
            },
            "warnings": [],
        }

        def fake_run_calculate(_config: BotConfig, values: dict[str, str]) -> dict[str, object]:
            self.assertEqual(values["service_fee_per_ton"], "15")
            self.assertEqual(values["broker_fee_per_ton"], "3")
            return {
                "inputs": values.copy(),
                "results": {
                    "scale_weight": "29.93",
                    "factory_amount": "52300.00",
                    "customer_service_fee": "448.95",
                    "customer_broker_fee": "89.79",
                    "customer_amount": "51851.05",
                },
                "labels": {},
            }

        payload = {
            "event": {
                "action": {
                    "value": {"action": FEE_FORM_ACTION, "session_id": session.session_id},
                    "form_value": {SERVICE_FEE_FIELD: "15", BROKER_FEE_FIELD: "3"},
                }
            }
        }
        with patch("feishu_bot.main.run_recognize", return_value=recognize_result), patch(
            "feishu_bot.main.run_calculate", side_effect=fake_run_calculate
        ):
            response = service._handle_card_action_payload(payload)

        self.assertEqual(response["toast"]["type"], "info")
        self.assertEqual(api.cards, [])
        self.assertGreaterEqual(len(api.updates), 2)
        final_update = json.dumps(api.updates[-1]["card"], ensure_ascii=False)
        self.assertIn("51851.05", final_update)
        self.assertIn("448.95", final_update)


if __name__ == "__main__":
    unittest.main()
