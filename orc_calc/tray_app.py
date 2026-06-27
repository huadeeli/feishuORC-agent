from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from . import api
from .runtime_paths import logs_dir
from .server import RUNTIME_STATUS_PATH, ServerHandle, start_service


DOUBLE_CLICK_SECONDS = 0.55


def main() -> int:
    if os.name != "nt":
        from .server import serve

        serve(open_browser=True)
        return 0

    if _open_running_service():
        return 0

    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as exc:
        _log_error(exc)
        # Fallback keeps the calculator usable even if the tray package is missing.
        from .server import serve

        serve(open_browser=True)
        return 0

    app = _TrayApp(pystray, Image, ImageDraw)
    return app.run()


class _TrayApp:
    def __init__(self, pystray_module: Any, image_module: Any, draw_module: Any) -> None:
        self.pystray = pystray_module
        self.Image = image_module
        self.ImageDraw = draw_module
        self.handle: ServerHandle | None = None
        self.icon: Any | None = None
        self._stopping = False
        self._stop_event = threading.Event()
        self._last_tray_click = 0.0

    def run(self) -> int:
        try:
            self.handle = start_service(open_browser=True, runtime_mode="tray")
            menu = self.pystray.Menu(
                self.pystray.MenuItem("打开计算器", self._open_ui_from_tray, default=True, visible=False),
                self.pystray.MenuItem("打开计算器", self._open_ui),
                self.pystray.MenuItem("复制地址", self._copy_url),
                self.pystray.MenuItem("服务状态", self._show_status),
                self.pystray.Menu.SEPARATOR,
                self.pystray.MenuItem("退出", self._exit),
            )
            self.icon = self.pystray.Icon("orc-calc", self._create_icon_image(), "废纸 OCR 计算器", menu)
            self.icon.run_detached()
            self._stop_event.wait()
            return 0
        except Exception as exc:
            _log_error(exc)
            self._stop_service()
            return 1
        finally:
            self._stop_icon()
            self._stop_service()

    def _create_icon_image(self) -> Any:
        image = self.Image.new("RGBA", (64, 64), (20, 99, 210, 255))
        draw = self.ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=12, fill=(20, 99, 210, 255), outline=(255, 255, 255, 255), width=3)
        draw.rectangle((20, 16, 44, 48), fill=(255, 255, 255, 255))
        draw.rectangle((24, 22, 40, 26), fill=(20, 99, 210, 255))
        draw.rectangle((24, 31, 40, 35), fill=(20, 99, 210, 255))
        draw.rectangle((24, 40, 36, 44), fill=(20, 99, 210, 255))
        return image

    def _open_ui(self, icon: Any | None = None, item: Any | None = None) -> None:
        if self.handle:
            webbrowser.open(self.handle.url)

    def _open_ui_from_tray(self, icon: Any | None = None, item: Any | None = None) -> None:
        now = time.monotonic()
        if now - self._last_tray_click <= DOUBLE_CLICK_SECONDS:
            self._last_tray_click = 0.0
            self._open_ui(icon, item)
            return
        self._last_tray_click = now

    def _copy_url(self, icon: Any | None = None, item: Any | None = None) -> None:
        if not self.handle:
            return
        _copy_to_clipboard(self.handle.url)
        self._notify("地址已复制", self.handle.url)

    def _show_status(self, icon: Any | None = None, item: Any | None = None) -> None:
        url = self.handle.url if self.handle else "未启动"
        local = api.ocr_runtime_status()
        cloud = api.cloud_runtime_status()
        local_text = "已就绪" if local.get("ocr_ready") else "未就绪"
        cloud_text = "已配置" if cloud.get("cloud_configured") else "未配置"
        message = f"地址：{url}\n后台模式：托盘\n本地 OCR：{local_text}\n云端 OCR：{cloud_text}\n关闭浏览器不会退出服务。"
        self._notify("废纸 OCR 计算器", message)

    def _exit(self, icon: Any | None = None, item: Any | None = None) -> None:
        self._stopping = True
        self._stop_event.set()

    def _stop_icon(self) -> None:
        if not self.icon:
            return
        try:
            self.icon.stop()
        except Exception as exc:
            _log_error(exc)
        self.icon = None

    def _notify(self, title: str, message: str) -> None:
        if self.icon and hasattr(self.icon, "notify"):
            try:
                self.icon.notify(message, title)
                return
            except Exception as exc:
                _log_error(exc)
        _message_box(title, message)

    def _stop_service(self) -> None:
        if not self.handle:
            return
        try:
            self.handle.stop()
        except Exception as exc:
            _log_error(exc)
        self.handle = None


def _open_running_service() -> bool:
    status = _read_runtime_status()
    url = str(status.get("url") or "")
    if not url or status.get("runtime_mode") != "tray":
        return False
    try:
        with urllib.request.urlopen(f"{url}/api/v1/templates", timeout=1.5) as response:
            if response.status != 200:
                return False
        webbrowser.open(url)
        return True
    except Exception:
        _delete_stale_runtime_status(status)
        return False


def _read_runtime_status() -> dict[str, Any]:
    try:
        if RUNTIME_STATUS_PATH.exists():
            data = json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        _log_error(exc)
    return {}


def _delete_stale_runtime_status(status: dict[str, Any]) -> None:
    try:
        if not RUNTIME_STATUS_PATH.exists():
            return
        current = json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
        if current == status:
            RUNTIME_STATUS_PATH.unlink()
    except Exception:
        pass


def _copy_to_clipboard(text: str) -> None:
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception as exc:
        _log_error(exc)

    creationflags = 0x08000000 if os.name == "nt" else 0
    try:
        subprocess.run(
            ["clip.exe"],
            input=text,
            text=True,
            check=True,
            creationflags=creationflags,
        )
    except Exception as exc:
        _log_error(exc)


def _message_box(title: str, message: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0)
    except Exception as exc:
        _log_error(exc)


def _log_error(exc: BaseException) -> None:
    try:
        path = logs_dir() / "tray.log"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        message = f"{type(exc).__name__}: {exc}\n"
        path.write_text((existing + message)[-8000:], encoding="utf-8")
    except Exception:
        pass
