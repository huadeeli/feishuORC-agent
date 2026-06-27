from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_DIRS = [
    ROOT / "orc_calc" / "agent_adapters",
    ROOT / "feishu_bot",
]


class AgentAdapterBoundaryTests(unittest.TestCase):
    def test_agent_adapters_do_not_import_core_ocr_or_api(self) -> None:
        forbidden_prefixes = (
            "orc_calc.api",
            "orc_calc.core",
            "orc_calc.ocr",
            "orc_calc.server",
            "orc_calc.fastapi_app",
        )
        violations: list[str] = []

        for directory in ADAPTER_DIRS:
            for path in directory.glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(forbidden_prefixes):
                                violations.append(f"{path.name}: import {alias.name}")
                    elif isinstance(node, ast.ImportFrom):
                        module = node.module or ""
                        if module.startswith(forbidden_prefixes):
                            violations.append(f"{path.name}: from {module} import ...")

        self.assertEqual(
            violations,
            [],
            "Agent adapters must call the calculator through HTTP/CLI only.",
        )


if __name__ == "__main__":
    unittest.main()
