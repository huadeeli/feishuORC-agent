from __future__ import annotations

import argparse
import base64
import json
import urllib.request
from pathlib import Path


def call_calculator(
    image_path: str,
    *,
    endpoint: str = "http://127.0.0.1:8765/api/v1/recognize",
    ocr: str = "local",
    template_id: str = "auto",
    timeout: int = 900,
) -> dict:
    path = Path(image_path)
    payload = {
        "ocr": ocr,
        "template_id": template_id,
        "filename": path.name,
        "image_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def format_agent_reply(result: dict) -> str:
    fields = {item["label"]: item.get("value", "") for item in result.get("fields", [])}
    calc = result.get("calculation", {}).get("results", {})
    lines = [
        "识别结果",
        f"毛重: {fields.get('毛重', '')}",
        f"皮重: {fields.get('皮重', '')}",
        f"单价: {fields.get('单价', '')}",
        f"结算重量: {fields.get('结算重量', '')}",
        f"税费: {fields.get('税费', '')}",
        f"司磅重量: {calc.get('scale_weight', '')}",
        f"收厂钱: {calc.get('factory_amount', '')}",
        f"转客户钱: {calc.get('customer_amount', '')}",
    ]
    warnings = result.get("warnings") or []
    if warnings:
        lines.append("提醒: " + "；".join(warnings))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenClaw/Agent HTTP adapter sample")
    parser.add_argument("image")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8765/api/v1/recognize")
    parser.add_argument("--ocr", choices=["local", "local-fast", "fast", "cloud"], default="local")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--template", default="auto")
    args = parser.parse_args()
    print(
        format_agent_reply(
            call_calculator(args.image, endpoint=args.endpoint, ocr=args.ocr, template_id=args.template, timeout=args.timeout)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
