from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orc_calc import api  # noqa: E402
from orc_calc.core.calculator import calculate  # noqa: E402
from orc_calc.core.recognizer import OCRLine, recognize_from_ocr_lines  # noqa: E402
from orc_calc.ocr.base import OCRProviderResult  # noqa: E402


class CalculatorTests(unittest.TestCase):
    def test_jianhui_formula(self) -> None:
        result = calculate(
            {
                "gross_weight": "48.29",
                "tare_weight": "15.27",
                "unit_price": "1830",
                "settlement_weight": "30.84",
                "tax_fee": "894.05",
                "service_fee_per_ton": "0",
                "broker_fee_per_ton": "0",
            }
        )
        self.assertEqual(result["factory_amount"], "55543.15")

    def test_jingzhou_formula(self) -> None:
        result = calculate(
            {
                "gross_weight": "50.54",
                "tare_weight": "16.18",
                "unit_price": "1730",
                "settlement_weight": "32.669",
                "tax_fee": "895.33",
                "service_fee_per_ton": "0",
                "broker_fee_per_ton": "0",
            }
        )
        self.assertEqual(result["scale_weight"], "34.36")
        self.assertEqual(result["factory_amount"], "55622.04")

    def test_manual_fee_per_ton(self) -> None:
        result = calculate(
            {
                "gross_weight": "50",
                "tare_weight": "10",
                "unit_price": "1000",
                "settlement_weight": "39",
                "tax_fee": "100",
                "service_fee_per_ton": "2",
                "broker_fee_per_ton": "3",
            }
        )
        self.assertEqual(result["customer_service_fee"], "80.00")
        self.assertEqual(result["customer_broker_fee"], "120.00")
        self.assertEqual(result["customer_amount"], "38820.00")

    def test_customer_amount_deducts_service_fee_but_not_broker_fee(self) -> None:
        result = calculate(
            {
                "gross_weight": "45.74",
                "tare_weight": "15.81",
                "unit_price": "1800",
                "settlement_weight": "29.5",
                "tax_fee": "800",
                "service_fee_per_ton": "15",
                "broker_fee_per_ton": "3",
            }
        )
        self.assertEqual(result["scale_weight"], "29.93")
        self.assertEqual(result["factory_amount"], "52300.00")
        self.assertEqual(result["customer_service_fee"], "448.95")
        self.assertEqual(result["customer_broker_fee"], "89.79")
        self.assertEqual(result["customer_amount"], "51851.05")


class RecognitionTests(unittest.TestCase):
    def test_jianhui_template_matches_ocr_keywords(self) -> None:
        result = recognize_from_ocr_lines(
            [
                OCRLine("送货日期*", 0.99),
                OCRLine("毛重* 46.69", 0.98),
                OCRLine("皮重* 16.24", 0.97),
                OCRLine("结算重量* 28.83", 0.99),
                OCRLine("结算单价* 1870", 0.99),
                OCRLine("代办税额*", 0.96),
                OCRLine("854.05", 0.98),
                OCRLine("结算金额*", 0.99),
            ],
            template_id="auto",
            provider_name="test",
        )
        self.assertEqual(result["template"]["id"], "jianhui")
        fields = {field["key"]: field for field in result["fields"]}
        self.assertEqual(fields["tax_fee"]["value"], "854.05")

    def test_tax_fee_generic_alias_without_template(self) -> None:
        result = recognize_from_ocr_lines(
            [
                OCRLine("代办税额*", 0.96),
                OCRLine("854.05", 0.98),
            ],
            template_id="auto",
            provider_name="test",
        )
        self.assertIsNone(result["template"])
        fields = {field["key"]: field for field in result["fields"]}
        self.assertEqual(fields["tax_fee"]["value"], "854.05")

    def test_tax_fee_does_not_use_tax_included_amount(self) -> None:
        result = recognize_from_ocr_lines(
            [
                OCRLine("含税金额", 0.96),
                OCRLine("56517.37", 0.98),
                OCRLine("税款合计", 0.96),
                OCRLine("895.33", 0.98),
            ],
            template_id="auto",
            provider_name="test",
        )
        fields = {field["key"]: field for field in result["fields"]}
        self.assertEqual(fields["tax_fee"]["value"], "895.33")

    def test_zero_line_recognition_is_not_reported_as_success(self) -> None:
        with patch.dict("os.environ", {"ORC_CALC_DISABLE_LOCAL_OCR": "1"}):
            with self.assertRaises(api.RecognitionError):
                api.recognize(
                    {
                        "image_path": str(ROOT / "jianhui 模板.jpg"),
                        "filename": "jianhui 模板.jpg",
                        "ocr": "local",
                        "template_id": "auto",
                    }
                )

    def test_auto_mode_falls_back_when_cloud_is_unavailable(self) -> None:
        complete_lines = [
            OCRLine("毛重* 46.69", 0.98),
            OCRLine("皮重* 16.24", 0.97),
            OCRLine("结算重量* 28.83", 0.99),
            OCRLine("结算单价* 1870", 0.99),
            OCRLine("代办税额* 854.05", 0.98),
        ]

        class FakeProvider:
            def __init__(self, mode: str) -> None:
                self.mode = mode

            def recognize(self, image_path, *, image_filename=None):
                if self.mode == "cloud":
                    return OCRProviderResult("cloud", [], ["token missing"], {"model": "PP-OCRv5"})
                return OCRProviderResult("local", complete_lines, [], {"model": "PP-OCRv5_mobile"})

        with patch.dict(
            "os.environ",
            {"ORC_OCR_PRIMARY": "cloud", "ORC_OCR_FALLBACK": "local-fast"},
            clear=False,
        ), patch("orc_calc.api.get_provider", side_effect=lambda mode: FakeProvider(mode)):
            result = api.recognize(
                {
                    "image_path": str(ROOT / "jianhui 模板.jpg"),
                    "filename": "uploaded.jpg",
                    "ocr": "auto",
                    "template_id": "auto",
                }
            )
        self.assertEqual(result["ocr"]["selected_mode"], "local-fast")
        self.assertTrue(result["ocr"]["fallback_used"])
        self.assertEqual(result["ocr"]["model"], "PP-OCRv5_mobile")
        self.assertEqual(len(result["ocr"]["attempts"]), 2)

    def test_missing_required_field_triggers_fallback(self) -> None:
        incomplete = [
            OCRLine("毛重* 46.69", 0.98),
            OCRLine("皮重* 16.24", 0.97),
            OCRLine("结算重量* 28.83", 0.99),
            OCRLine("结算单价* 1870", 0.99),
        ]
        complete = [*incomplete, OCRLine("代办税额* 854.05", 0.98)]

        class FakeProvider:
            def __init__(self, lines):
                self.lines = lines

            def recognize(self, image_path, *, image_filename=None):
                return OCRProviderResult("fake", self.lines, [], {"model": "test"})

        providers = iter([FakeProvider(incomplete), FakeProvider(complete)])
        with patch.dict(
            "os.environ",
            {"ORC_OCR_PRIMARY": "cloud", "ORC_OCR_FALLBACK": "local-fast"},
            clear=False,
        ), patch("orc_calc.api.get_provider", side_effect=lambda mode: next(providers)):
            result = api.recognize(
                {
                    "image_path": str(ROOT / "jianhui 模板.jpg"),
                    "filename": "uploaded.jpg",
                    "ocr": "auto",
                }
            )
        self.assertIn("tax_fee", result["ocr"]["attempts"][0]["missing_fields"])
        self.assertEqual(result["ocr"]["selected_mode"], "local-fast")

    def test_all_engines_incomplete_raises(self) -> None:
        class EmptyProvider:
            def recognize(self, image_path, *, image_filename=None):
                return OCRProviderResult("empty", [], ["failed"], {"model": "test"})

        with patch.dict(
            "os.environ",
            {"ORC_OCR_PRIMARY": "cloud", "ORC_OCR_FALLBACK": "local-fast"},
            clear=False,
        ), patch("orc_calc.api.get_provider", return_value=EmptyProvider()):
            with self.assertRaises(api.RecognitionError):
                api.recognize(
                    {
                        "image_path": str(ROOT / "jianhui 模板.jpg"),
                        "filename": "uploaded.jpg",
                        "ocr": "auto",
                    }
                )


if __name__ == "__main__":
    unittest.main()
