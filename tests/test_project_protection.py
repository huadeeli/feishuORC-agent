from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE_SUFFIXES = {".py", ".bat", ".ps1", ".spec"}
CHECKED_SOURCE_DIRS = (ROOT / "feishu_bot", ROOT / "orc_calc")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _iter_executable_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix.lower() in EXECUTABLE_SUFFIXES:
            files.append(path)
    for directory in CHECKED_SOURCE_DIRS:
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in EXECUTABLE_SUFFIXES:
                files.append(path)
    return sorted(files)


class ProjectProtectionTests(unittest.TestCase):
    def test_executable_files_do_not_hardcode_old_project_path(self) -> None:
        old_project_name = "废纸专用" + "ORC计算器"
        old_project_path = "D:\\AI\\" + old_project_name
        forbidden_markers = (old_project_path, old_project_name)
        violations: list[str] = []

        for path in _iter_executable_files():
            text = _read_text(path)
            for marker in forbidden_markers:
                if marker in text:
                    violations.append(f"{path.relative_to(ROOT)} contains {marker}")

        self.assertEqual(
            violations,
            [],
            "New Feishu project code/scripts must not reference the old ORC project path.",
        )

    def test_feishu_launch_scripts_pin_requested_ocr_modes(self) -> None:
        local = _read_text(ROOT / "run_feishu_bot_local.bat").lower()
        cloud = _read_text(ROOT / "run_feishu_bot_cloud.bat").lower()
        default = _read_text(ROOT / "run_feishu_bot.bat").lower()

        self.assertIn("set orc_ocr_mode=local", local)
        self.assertIn("call run_feishu_bot.bat", local)
        self.assertIn("set orc_ocr_mode=cloud", cloud)
        self.assertIn("call run_feishu_bot.bat", cloud)
        self.assertIn("-m feishu_bot.main", default)

    def test_feishu_tray_launch_scripts_use_tray_app_and_modes(self) -> None:
        tray = _read_text(ROOT / "run_feishu_bot_tray.bat").lower()
        local = _read_text(ROOT / "run_feishu_bot_tray_local.bat").lower()
        cloud = _read_text(ROOT / "run_feishu_bot_tray_cloud.bat").lower()

        self.assertIn("pythonw.exe", tray)
        self.assertIn("-m feishu_bot.tray_app", tray)
        self.assertIn("set orc_ocr_mode=local", local)
        self.assertIn("call run_feishu_bot_tray.bat", local)
        self.assertIn("set orc_ocr_mode=cloud", cloud)
        self.assertIn("call run_feishu_bot_tray.bat", cloud)

    def test_project_protection_script_includes_card_tests(self) -> None:
        script = _read_text(ROOT / "check_project_protection.bat")
        self.assertIn("tests.test_feishu_cards", script)

    def test_default_config_is_cloud_first_with_mobile_fallback(self) -> None:
        env_example = _read_text(ROOT / ".env.example")
        self.assertIn("ORC_OCR_MODE=auto", env_example)
        self.assertIn("ORC_OCR_PRIMARY=cloud", env_example)
        self.assertIn("ORC_OCR_FALLBACK=local-fast", env_example)
        self.assertIn("PADDLEOCR_ACCESS_TOKEN=", env_example)
        self.assertIn("ORC_FEISHU_SDK_LOG_LEVEL=WARNING", env_example)

    def test_cli_executable_is_windowed(self) -> None:
        spec = _read_text(ROOT / "orc-calc-cli.spec")
        self.assertIn("console=False", spec)

    def test_portable_check_requires_persistent_service_and_mobile_models(self) -> None:
        script = _read_text(ROOT / "packaging" / "portable" / "check-runtime.bat")
        self.assertIn("orc-calc.exe", script)
        self.assertIn("PP-OCRv5_mobile_det", script)
        self.assertIn("PP-OCRv5_mobile_rec", script)

    def test_source_tree_does_not_contain_runtime_env(self) -> None:
        self.assertFalse((ROOT / ".env").exists())

    def test_project_record_documents_card_fallback_and_calculation_process(self) -> None:
        record = _read_text(ROOT / "docs" / "project_protection_record.md")
        self.assertIn("飞书卡片输出", record)
        self.assertIn("计算过程", record)
        self.assertIn("卡片失败自动回退纯文本", record)
        self.assertIn("供应商、日期、车牌", record)
        self.assertIn("不参与公式计算", record)
        self.assertIn("发货单位", record)
        self.assertIn("供货日期", record)
        self.assertIn("结算金额/结算金", record)
        self.assertIn("含税金额", record)
        self.assertIn("未识别到结算金额必须显示验证不通过", record)
        self.assertIn("转客户钱名称和结果使用红色高亮", record)
        self.assertIn("手续费和中介费仍为蓝色普通文字", record)

    def test_project_record_documents_fee_form_runtime_and_auto_fallback(self) -> None:
        record = _read_text(ROOT / "docs" / "project_protection_record.md")
        self.assertIn("ORC_FEISHU_IMAGE_WORKFLOW=form", record)
        self.assertIn("ORC_FEISHU_IMAGE_WORKFLOW=auto", record)
        self.assertIn("runtime/feishu/card_sessions", record)
        self.assertIn("飞书卡片表单实测", record)
        self.assertIn("聊天上传图片", record)
        self.assertIn("识别并计算", record)


if __name__ == "__main__":
    unittest.main()
