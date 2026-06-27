from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from feishu_bot.config import BotConfig
from feishu_bot.main import (
    apply_text_overrides,
    extract_incoming_resource,
    extract_incoming_text,
    extract_post_image_key,
    extract_post_text,
    parse_calculation_text,
    parse_labeled_values,
)
from feishu_bot.message_format import format_calculation_reply, format_recognition_reply, help_text, parse_message_content
from feishu_bot.orc_cli import build_recognize_command, parse_json_output, run_calculate


class FeishuBotTests(unittest.TestCase):
    def test_parse_message_content_accepts_json_string(self) -> None:
        self.assertEqual(parse_message_content('{"image_key":"img_1"}'), {"image_key": "img_1"})

    def test_extract_incoming_image_resource(self) -> None:
        payload = {
            "event": {
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_1",
                    "message_type": "image",
                    "content": '{"image_key":"img_1"}',
                }
            }
        }
        incoming = extract_incoming_resource(payload)
        self.assertIsNotNone(incoming)
        assert incoming is not None
        self.assertEqual(incoming.file_key, "img_1")
        self.assertEqual(incoming.resource_type, "image")

    def test_extract_incoming_post_image_resource(self) -> None:
        content = {
            "title": "",
            "content": [
                [
                    {"tag": "img", "image_key": "img_v3_1", "width": 720, "height": 2200},
                    {"tag": "text", "text": "手续费15，中介费3元", "style": []},
                ]
            ],
        }
        payload = {
            "event": {
                "message": {
                    "message_id": "om_3",
                    "chat_id": "oc_1",
                    "message_type": "post",
                    "content": __import__("json").dumps(content, ensure_ascii=False),
                }
            }
        }
        incoming = extract_incoming_resource(payload)
        self.assertIsNotNone(incoming)
        assert incoming is not None
        self.assertEqual(incoming.file_key, "img_v3_1")
        self.assertEqual(incoming.resource_type, "image")
        self.assertEqual(incoming.note_text, "手续费15，中介费3元")
        self.assertEqual(extract_post_image_key(content), "img_v3_1")
        self.assertEqual(extract_post_text(content), "手续费15，中介费3元")

    def test_format_recognition_reply(self) -> None:
        result = {
            "fields": [
                {"label": "毛重", "value": "48.88"},
                {"label": "皮重", "value": "15.71"},
                {"label": "单价", "value": "1850"},
                {"label": "结算重量", "value": "31.876"},
                {"label": "税费", "value": "934.19"},
            ],
            "calculation": {
                "results": {
                    "scale_weight": "33.17",
                    "factory_amount": "58036.41",
                    "customer_amount": "57638.30",
                }
            },
        }
        reply = format_recognition_reply(result)
        self.assertIn("识别完成", reply)
        self.assertIn("毛重: 48.88", reply)
        self.assertIn("转客户钱: 57638.30", reply)

    def test_extract_incoming_text(self) -> None:
        payload = {
            "event": {
                "message": {
                    "message_id": "om_2",
                    "chat_id": "oc_1",
                    "message_type": "text",
                    "content": '{"text":"123"}',
                }
            }
        }
        incoming = extract_incoming_text(payload)
        self.assertIsNotNone(incoming)
        assert incoming is not None
        self.assertEqual(incoming.text, "123")

    def test_parse_calculation_text(self) -> None:
        values = parse_calculation_text("毛重45.74 皮重15.81 单价1800 结算重量29.5 税费800 手续费15")
        self.assertEqual(values["gross_weight"], "45.74")
        self.assertEqual(values["service_fee_per_ton"], "15")

    def test_parse_labeled_values_allows_fee_only(self) -> None:
        self.assertEqual(parse_labeled_values("手续费15"), {"service_fee_per_ton": "15"})

    def test_parse_labeled_values_reads_service_and_broker_fee(self) -> None:
        self.assertEqual(
            parse_labeled_values("手续费15，中介费3元"),
            {"service_fee_per_ton": "15", "broker_fee_per_ton": "3"},
        )

    def test_apply_text_overrides_recalculates_with_broker_fee_kept_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = BotConfig(
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
                reply_style="card",
                image_workflow="auto",
                ack_text="ack",
                unsupported_text="unsupported",
            )
            result = {
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
                }
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

            with patch("feishu_bot.main.run_calculate", side_effect=fake_run_calculate):
                updated = apply_text_overrides(config, result, "手续费15，中介费3元")

        calculation = updated["calculation"]
        self.assertEqual(calculation["inputs"]["service_fee_per_ton"], "15")
        self.assertEqual(calculation["inputs"]["broker_fee_per_ton"], "3")
        self.assertEqual(calculation["results"]["customer_broker_fee"], "89.79")
        self.assertEqual(calculation["results"]["customer_amount"], "51851.05")

    def test_help_text_mentions_image_and_text(self) -> None:
        text = help_text()
        self.assertIn("发图片", text)
        self.assertIn("发文字", text)

    def test_format_calculation_reply(self) -> None:
        reply = format_calculation_reply(
            {
                "inputs": {"gross_weight": "45.74", "tare_weight": "15.81"},
                "results": {"scale_weight": "29.93", "factory_amount": "52300.00", "customer_amount": "51851.05"},
                "labels": {},
            }
        )
        self.assertIn("文字计算完成", reply)
        self.assertIn("司磅重量: 29.93", reply)

    def test_cli_command_uses_configured_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = BotConfig(
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
                reply_style="card",
                image_workflow="auto",
                ack_text="ack",
                unsupported_text="unsupported",
            )
            command = build_recognize_command(config, root / "image.jpg")
            joined = " ".join(command)
            self.assertIn(str(root / "orc-calc.py"), joined)
            self.assertNotIn("废纸专用ORC计算器", joined)

    def test_run_calculate_can_call_packaged_cli_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli_path = root / "orc-calc-cli.exe"
            config = BotConfig(
                app_id="",
                app_secret="",
                ocr_mode="local",
                template_id="auto",
                cli_path=cli_path,
                python_executable="python.exe",
                project_root=root,
                runtime_dir=root / "runtime" / "feishu",
                downloads_dir=root / "runtime" / "feishu" / "downloads",
                log_file=root / "runtime" / "feishu" / "logs" / "feishu_bot.log",
                command_timeout=900,
                max_workers=2,
                feishu_base_url="https://open.feishu.cn",
                log_level="DEBUG",
                reply_style="card",
                image_workflow="auto",
                ack_text="ack",
                unsupported_text="unsupported",
            )

            class Completed:
                returncode = 0
                stdout = '{"ok": true}'
                stderr = ""

            with patch("feishu_bot.orc_cli.subprocess.run", return_value=Completed()) as mocked_run:
                result = run_calculate(config, {"gross_weight": "10"})

            command = mocked_run.call_args.args[0]
            self.assertEqual(command[0], str(cli_path))
            self.assertEqual(command[1], "calculate")
            self.assertEqual(result, {"ok": True})

    def test_parse_json_output_ignores_leading_log_text(self) -> None:
        self.assertEqual(parse_json_output('log line\n{"ok": true}'), {"ok": True})


if __name__ == "__main__":
    unittest.main()
