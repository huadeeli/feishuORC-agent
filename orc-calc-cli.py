from __future__ import annotations

import sys
import traceback

from orc_calc.cli import main
from orc_calc.runtime_paths import logs_dir


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception:
        (logs_dir() / "fatal-cli.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
