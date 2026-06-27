from __future__ import annotations

import sys
import traceback
from pathlib import Path

from feishu_bot.tray_app import main


def _log_path() -> Path:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    path = root / "runtime" / "feishu" / "logs" / "fatal-feishu-bot-tray.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:
        _log_path().write_text(traceback.format_exc(), encoding="utf-8")
        raise
