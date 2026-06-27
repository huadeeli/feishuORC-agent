from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import api
from .server import serve


def main(argv: list[str] | None = None) -> int:
    _configure_console_output()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        serve(args.host, args.port, args.open)
        return 0

    if args.command == "recognize":
        payload = {
            "image_path": str(Path(args.image).resolve()),
            "filename": Path(args.image).name,
            "ocr": args.ocr,
            "template_id": args.template,
        }
        result = api.recognize(payload)
        _print_result(result, as_json=args.json)
        return 0

    if args.command == "calculate":
        values = dict(item.split("=", 1) for item in args.values)
        result = api.calculate({"values": values})
        _print_result(result, as_json=True)
        return 0

    if args.command == "health":
        _print_result(api.health(), as_json=True)
        return 0

    if args.command == "ocr-check":
        _print_result(api.ocr_check(), as_json=True)
        return 0

    if args.command == "cloud-check":
        payload = {"image_path": str(Path(args.image).resolve())} if args.image else {}
        _print_result(api.cloud_check(payload), as_json=True)
        return 0

    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orc-calc", description="废纸 OCR 图片计算器")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="启动本地网页/API 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    serve_parser.set_defaults(open=False)

    recognize_parser = subparsers.add_parser("recognize", help="识别图片并输出结果")
    recognize_parser.add_argument("image")
    recognize_parser.add_argument("--ocr", choices=["auto", "local", "fast", "local-fast", "cloud"], default="auto")
    recognize_parser.add_argument("--template", default="auto")
    recognize_parser.add_argument("--json", action="store_true")

    calculate_parser = subparsers.add_parser("calculate", help="仅按字段计算")
    calculate_parser.add_argument("values", nargs="+", help="形如 gross_weight=50.54")

    subparsers.add_parser("health", help="输出服务健康状态，并真实加载本地 OCR 模型")
    subparsers.add_parser("ocr-check", help="真实启动 worker 并加载本地 OCR 模型")
    cloud_parser = subparsers.add_parser("cloud-check", help="检查官方云端 PaddleOCR API 配置")
    cloud_parser.add_argument("--image", default="", help="可选，提交图片做真实云端识别测试")
    parser.set_defaults(host="127.0.0.1", port=8765, open=True)
    return parser


def _print_result(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    fields = result.get("fields", [])
    calculation = result.get("calculation", {}).get("results", {})
    for field in fields:
        print(f"{field.get('label')}: {field.get('value')}  置信度 {field.get('confidence')}")
    for key, value in calculation.items():
        print(f"{key}: {value}")


def _configure_console_output() -> None:
    if sys.stdout is None:
        try:
            sys.stdout = open(1, "w", encoding="utf-8", errors="replace", closefd=False)
        except OSError:
            pass
    if sys.stderr is None:
        try:
            sys.stderr = open(2, "w", encoding="utf-8", errors="replace", closefd=False)
        except OSError:
            pass
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
