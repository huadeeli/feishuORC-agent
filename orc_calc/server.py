from __future__ import annotations

import errno
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import api
from .core.templates import PROJECT_ROOT
from .runtime_paths import runtime_dir


STATIC_DIR = PROJECT_ROOT / "static"
RUNTIME_STATUS_PATH = runtime_dir() / "server.json"


@dataclass
class ServerHandle:
    httpd: ThreadingHTTPServer
    host: str
    port: int
    runtime_mode: str = "service"
    thread: threading.Thread | None = field(default=None, init=False)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self, *, open_browser: bool = False) -> "ServerHandle":
        if self.thread and self.thread.is_alive():
            return self
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
        )
        self.thread.start()
        _write_runtime_status(self)
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(self.url)).start()
        return self

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        finally:
            self.httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        _clear_runtime_status(self)


class CalculatorRequestHandler(BaseHTTPRequestHandler):
    server_version = "OrcCalcHTTP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/v1/health":
            self._json(api.health())
        elif path == "/api/v1/cloud-check":
            self._json(api.cloud_check())
        elif path == "/api/v1/templates":
            self._json(api.templates())
        elif path == "/api/v1/openapi.json":
            self._json(api.api_spec())
        elif path == "/api/v1/docs":
            self._html(_docs_html())
        elif path == "/sample/jianhui":
            self._file(PROJECT_ROOT / "jianhui 模板.jpg")
        elif path == "/sample/jingzhou":
            self._file(PROJECT_ROOT / "jingzhou 模板.jpg")
        elif path == "/":
            self._file(STATIC_DIR / "index.html")
        else:
            relative = unquote(path.lstrip("/"))
            candidate = (STATIC_DIR / relative).resolve()
            try:
                candidate.relative_to(STATIC_DIR.resolve())
            except ValueError:
                self._error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            self._file(candidate)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            if parsed.path == "/api/v1/recognize":
                self._json(api.recognize(payload))
            elif parsed.path == "/api/v1/warmup":
                self._json(api.warmup(payload))
            elif parsed.path == "/api/v1/calculate":
                self._json(api.calculate(payload))
            else:
                self._error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = api.dumps_json(data)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._error(HTTPStatus.NOT_FOUND, "Not found")
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"ok": False, "error": message}, status=status)


def start_service(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    runtime_mode: str = "service",
) -> ServerHandle:
    httpd, selected_port = _create_server(host, port)
    if selected_port != port:
        _safe_print(f"Port {port} is busy, switched to {selected_port}.")
    handle = ServerHandle(httpd=httpd, host=host, port=selected_port, runtime_mode=runtime_mode)
    handle.start(open_browser=open_browser)
    _safe_print(f"OCR calculator started: {handle.url}")
    return handle


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    handle = start_service(host, port, open_browser, runtime_mode="cli")
    _safe_print("Press Ctrl+C to stop.")
    try:
        while handle.thread and handle.thread.is_alive():
            handle.thread.join(timeout=0.5)
    except KeyboardInterrupt:
        handle.stop()


def _create_server(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    last_error: OSError | None = None
    for selected_port in range(port, port + 20):
        if _port_has_listener(host, selected_port):
            continue
        try:
            return ThreadingHTTPServer((host, selected_port), CalculatorRequestHandler), selected_port
        except OSError as exc:
            last_error = exc
            if not _is_port_in_use(exc):
                raise
    raise OSError(f"No available port in range {port}-{port + 19}") from last_error


def _is_port_in_use(exc: OSError) -> bool:
    return exc.errno in {errno.EADDRINUSE, 10048}


def _port_has_listener(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _write_runtime_status(handle: ServerHandle) -> None:
    payload = {
        "pid": os.getpid(),
        "host": handle.host,
        "port": handle.port,
        "url": handle.url,
        "runtime_mode": handle.runtime_mode,
        "started_at": int(time.time()),
    }
    try:
        RUNTIME_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clear_runtime_status(handle: ServerHandle) -> None:
    try:
        if not RUNTIME_STATUS_PATH.exists():
            return
        payload = json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
        if payload.get("pid") == os.getpid() and int(payload.get("port", 0)) == handle.port:
            RUNTIME_STATUS_PATH.unlink()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass


def _safe_print(message: str) -> None:
    try:
        print(message, flush=True)
    except Exception:
        try:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            pass


def _docs_html() -> str:
    spec = json.dumps(api.api_spec(), ensure_ascii=False, indent=2)
    escaped = spec.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>废纸 OCR 计算器 API</title>
  <style>
    body {{ margin: 0; font-family: Arial, 'Microsoft YaHei', sans-serif; background: #f5f7fb; color: #172033; }}
    main {{ max-width: 960px; margin: 40px auto; padding: 0 24px; }}
    h1 {{ font-size: 28px; }}
    pre {{ background: #0f172a; color: #e2e8f0; padding: 20px; overflow: auto; border-radius: 8px; }}
    code {{ font-family: Consolas, monospace; }}
  </style>
</head>
<body>
<main>
  <h1>废纸 OCR 计算器 API</h1>
  <p>Agent、OpenClaw、飞书或 Telegram 适配器只调用这些接口，不直接修改计算器核心。</p>
  <pre><code>{escaped}</code></pre>
</main>
</body>
</html>"""
