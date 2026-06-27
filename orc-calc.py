from __future__ import annotations

import os
import sys
import traceback

from orc_calc.cli import main
from orc_calc.runtime_paths import logs_dir
from orc_calc.tray_app import main as tray_main


if __name__ == "__main__":
    try:
        if len(sys.argv) == 1 and os.name == "nt":
            raise SystemExit(tray_main())
        raise SystemExit(main(sys.argv[1:]))
    except Exception:
        (logs_dir() / "fatal.log").write_text(traceback.format_exc(), encoding="utf-8")
        if len(sys.argv) > 1:
            raise
        raise SystemExit(1)
