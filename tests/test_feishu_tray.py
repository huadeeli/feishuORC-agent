from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import feishu_bot.tray_app as tray_app
from feishu_bot.tray_app import (
    WINDOW_CLOSE_ACTION,
    build_bot_command,
    build_bot_environment,
    build_service_command,
)


class FeishuTrayTests(unittest.TestCase):
    def test_build_bot_command_runs_feishu_main_module(self) -> None:
        self.assertEqual(build_bot_command("python.exe"), ["python.exe", "-m", "feishu_bot.main"])

    def test_frozen_tray_command_runs_sibling_bot_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tray_exe = root / "feishu-bot-tray.exe"
            bot_exe = root / "feishu-bot.exe"
            bot_exe.write_text("", encoding="utf-8")
            with patch.object(tray_app.sys, "executable", str(tray_exe)), patch.object(
                tray_app.sys, "frozen", True, create=True
            ):
                command = build_bot_command()

            self.assertEqual(len(command), 1)
            self.assertTrue(Path(command[0]).samefile(bot_exe))

    def test_build_bot_environment_sets_mode_and_cli_python(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            env = build_bot_environment(
                mode="auto",
                python_executable="python.exe",
                service_url="http://127.0.0.1:8765",
            )

        self.assertEqual(env["ORC_OCR_MODE"], "auto")
        self.assertEqual(env["ORC_OCR_SERVICE_URL"], "http://127.0.0.1:8765")
        self.assertEqual(env["ORC_PYTHON"], "python.exe")
        self.assertEqual(env["PYTHONIOENCODING"], "utf-8")

    def test_build_service_command_runs_persistent_api(self) -> None:
        command = build_service_command("127.0.0.1", 8765, "python.exe")
        self.assertEqual(
            command,
            ["python.exe", "-m", "orc_calc.cli", "serve", "--host", "127.0.0.1", "--port", "8765"],
        )

    def test_window_close_action_is_hide(self) -> None:
        self.assertEqual(WINDOW_CLOSE_ACTION, "hide")

    def test_duplicate_instance_exits_without_blocking_message_box(self) -> None:
        source = Path(tray_app.__file__).read_text(encoding="utf-8")
        duplicate_block = source.split("if not acquire_single_instance():", 1)[1].split("try:", 1)[0]
        self.assertIn("return 0", duplicate_block)
        self.assertNotIn("_message_box", duplicate_block)


if __name__ == "__main__":
    unittest.main()
