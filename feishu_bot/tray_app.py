from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import BotConfig, ConfigError, ensure_runtime_dirs, load_config


WINDOW_CLOSE_ACTION = "hide"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
ERROR_ALREADY_EXISTS = 183
SINGLE_INSTANCE_NAME = "Local\\WastePaperOrcFeishuTray"
_INSTANCE_MUTEX: Any | None = None


def console_python_executable() -> str:
    current = Path(sys.executable)
    if current.name.lower() == "pythonw.exe":
        candidate = current.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return str(current)


def build_bot_command(python_executable: str | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        sibling_bot = Path(sys.executable).resolve().with_name("feishu-bot.exe")
        if sibling_bot.exists():
            return [str(sibling_bot)]
    return [python_executable or console_python_executable(), "-m", "feishu_bot.main"]


def build_service_command(host: str, port: int, python_executable: str | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        sibling_service = Path(sys.executable).resolve().with_name("orc-calc.exe")
        if sibling_service.exists():
            return [str(sibling_service), "serve", "--host", host, "--port", str(port)]
    return [
        python_executable or console_python_executable(),
        "-m",
        "orc_calc.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]


def build_bot_environment(
    *,
    mode: str | None = None,
    python_executable: str | None = None,
    service_url: str | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if mode:
        env["ORC_OCR_MODE"] = mode
    if service_url:
        env["ORC_OCR_SERVICE_URL"] = service_url
    env.setdefault("ORC_PYTHON", python_executable or console_python_executable())
    return env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feishu ORC bot tray launcher")
    parser.add_argument("--mode", choices=("auto", "local", "local-fast", "cloud"), default=None)
    args = parser.parse_args(argv)

    if os.name != "nt":
        print("Feishu tray mode is intended for Windows. Starting console bot instead.")
        from .main import main as bot_main

        return bot_main([])

    if not acquire_single_instance():
        return 0

    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as exc:
        _message_box("废纸 ORC 飞书机器人", f"托盘依赖不可用：{exc}\n请运行 setup_feishu_env.bat 后再试。")
        return 1

    try:
        config = load_config(require_credentials=False)
        ensure_runtime_dirs(config)
    except ConfigError as exc:
        _message_box("废纸 ORC 飞书机器人", f"配置错误：{exc}")
        return 2

    app = FeishuBotTrayApp(config=config, mode=args.mode, pystray_module=pystray, image_module=Image, draw_module=ImageDraw)
    return app.run()


class FeishuBotTrayApp:
    def __init__(
        self,
        *,
        config: BotConfig,
        mode: str | None,
        pystray_module: Any,
        image_module: Any,
        draw_module: Any,
    ) -> None:
        self.config = config
        self.mode = mode or config.ocr_mode
        self.pystray = pystray_module
        self.Image = image_module
        self.ImageDraw = draw_module
        self.process: subprocess.Popen[Any] | None = None
        self.service_process: subprocess.Popen[Any] | None = None
        self.icon: Any | None = None
        self.root: Any | None = None
        self.status_var: Any | None = None
        self.log_text: Any | None = None
        self._exiting = False
        self._log_stream: Any | None = None
        self._service_log_stream: Any | None = None
        self.service_host = "127.0.0.1"
        self.service_port = _find_free_port(self.service_host, 8765)
        self.service_url = f"http://{self.service_host}:{self.service_port}"
        self.warmup_status = "等待预热"
        self.tray_log_file = self.config.log_file.parent / "feishu_bot_tray.log"
        self.service_log_file = self.config.log_file.parent / "ocr_service.log"

    def run(self) -> int:
        try:
            self._setup_window()
            self._start_service()
            self._start_bot()
            threading.Thread(target=self._warmup_service, daemon=True).start()
            self._setup_icon()
            self._refresh_status()
            self.root.mainloop()
            return 0
        except Exception as exc:
            _write_log(self.tray_log_file, f"{type(exc).__name__}: {exc}\n")
            _message_box("废纸 ORC 飞书机器人", f"托盘启动失败：{exc}")
            return 1
        finally:
            self._stop_icon()
            self._stop_bot()
            self._stop_service()

    def show_window(self, icon: Any | None = None, item: Any | None = None) -> None:
        if not self.root:
            return
        self.root.after(0, self._show_window)

    def hide_window(self) -> None:
        if self.root:
            self.root.withdraw()
        self._notify("废纸 ORC 飞书机器人", "窗口已隐藏，机器人仍在后台运行。可从托盘图标重新打开。")

    def restart_bot(self, icon: Any | None = None, item: Any | None = None) -> None:
        if not self.root:
            return
        self.root.after(0, self._restart_bot)

    def open_log(self, icon: Any | None = None, item: Any | None = None) -> None:
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.log_file.exists():
            self.config.log_file.write_text("", encoding="utf-8")
        try:
            os.startfile(str(self.config.log_file))
        except Exception as exc:
            _write_log(self.tray_log_file, f"open log failed: {exc}\n")

    def exit_app(self, icon: Any | None = None, item: Any | None = None) -> None:
        if not self.root:
            return
        self.root.after(0, self._exit_app)

    def _setup_window(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.root = tk.Tk()
        self.root.title("废纸 ORC 飞书机器人")
        self.root.geometry("520x330")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        title = ttk.Label(frame, text="废纸 ORC 飞书机器人", font=("Microsoft YaHei UI", 13, "bold"))
        title.pack(anchor="w")

        self.status_var = tk.StringVar(value="正在启动...")
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", pady=(8, 10))

        hint = "点窗口右上角 X 只会隐藏窗口，不会关闭机器人。真正退出请右键托盘图标选择“退出”。"
        ttk.Label(frame, text=hint, wraplength=480).pack(anchor="w", pady=(0, 10))

        button_frame = ttk.Frame(frame)
        button_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(button_frame, text="重新启动机器人", command=self._restart_bot).pack(side="left")
        ttk.Button(button_frame, text="打开日志", command=self.open_log).pack(side="left", padx=(8, 0))
        ttk.Button(button_frame, text="隐藏到托盘", command=self.hide_window).pack(side="left", padx=(8, 0))

        self.log_text = tk.Text(frame, height=9, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _setup_icon(self) -> None:
        menu = self.pystray.Menu(
            self.pystray.MenuItem("显示窗口", self.show_window, default=True),
            self.pystray.MenuItem("重新启动机器人", self.restart_bot),
            self.pystray.MenuItem("打开日志", self.open_log),
            self.pystray.Menu.SEPARATOR,
            self.pystray.MenuItem("退出", self.exit_app),
        )
        self.icon = self.pystray.Icon("orc-feishu-bot", self._create_icon_image(), "废纸 ORC 飞书机器人", menu)
        self.icon.run_detached()

    def _create_icon_image(self) -> Any:
        image = self.Image.new("RGBA", (64, 64), (255, 187, 0, 255))
        draw = self.ImageDraw.Draw(image)
        draw.rounded_rectangle((6, 6, 58, 58), radius=12, fill=(255, 187, 0, 255), outline=(255, 255, 255, 255), width=3)
        draw.polygon([(32, 12), (48, 21), (48, 43), (32, 52), (16, 43), (16, 21)], fill=(255, 255, 255, 255))
        draw.line([(32, 12), (32, 52)], fill=(255, 187, 0, 255), width=3)
        draw.line([(16, 21), (32, 31), (48, 21)], fill=(255, 187, 0, 255), width=3)
        return image

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _start_bot(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        _write_log(self.tray_log_file, f"\n[{_timestamp()}] starting Feishu bot, mode={self.mode}\n")
        self._log_stream = self.tray_log_file.open("a", encoding="utf-8", errors="replace")
        command = build_bot_command()
        env = build_bot_environment(mode=self.mode, service_url=self.service_url)
        self.process = subprocess.Popen(
            command,
            cwd=self.config.project_root,
            env=env,
            stdout=self._log_stream,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._wait_for_bot_exit, daemon=True).start()

    def _start_service(self) -> None:
        if self.service_process and self.service_process.poll() is None:
            return
        self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
        _write_log(self.tray_log_file, f"[{_timestamp()}] starting OCR service at {self.service_url}\n")
        _rotate_log(self.service_log_file)
        self._service_log_stream = self.service_log_file.open("a", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["ORC_OCR_MODE"] = self.mode
        command = build_service_command(self.service_host, self.service_port)
        self.service_process = subprocess.Popen(
            command,
            cwd=self.config.project_root,
            env=env,
            stdout=self._service_log_stream,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.service_process.poll() is not None:
                raise RuntimeError(f"OCR service exited with code {self.service_process.returncode}")
            if _service_is_ready(self.service_url):
                return
            time.sleep(0.25)
        raise RuntimeError("OCR service did not become ready within 20 seconds")

    def _warmup_service(self) -> None:
        self.warmup_status = "正在预热 mobile 模型"
        if self.root:
            self.root.after(0, self._refresh_status)
        started = time.monotonic()
        try:
            result = _post_service_json(
                f"{self.service_url}/api/v1/warmup",
                {"ocr": "local-fast"},
                timeout=self.config.command_timeout,
            )
            elapsed = float(result.get("elapsed_ms") or ((time.monotonic() - started) * 1000)) / 1000
            self.warmup_status = f"mobile 已预热（{elapsed:.1f}秒）"
            _write_log(
                self.tray_log_file,
                f"[{_timestamp()}] OCR warmup complete model={result.get('model')} "
                f"lines={result.get('line_count')} elapsed_ms={result.get('elapsed_ms')}\n",
            )
        except Exception as exc:
            self.warmup_status = "预热失败，首次识别时重试"
            _write_log(self.tray_log_file, f"[{_timestamp()}] OCR warmup failed: {exc}\n")
        if self.root:
            self.root.after(0, self._refresh_status)

    def _stop_bot(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        if self._log_stream:
            try:
                self._log_stream.close()
            except Exception:
                pass
        self._log_stream = None

    def _stop_service(self) -> None:
        if self.service_process and self.service_process.poll() is None:
            self.service_process.terminate()
            try:
                self.service_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.service_process.kill()
                self.service_process.wait(timeout=5)
        self.service_process = None
        if self._service_log_stream:
            try:
                self._service_log_stream.close()
            except Exception:
                pass
        self._service_log_stream = None

    def _restart_bot(self) -> None:
        self._set_status("正在重新启动机器人...")
        self._stop_bot()
        self._start_bot()
        self._refresh_status()

    def _wait_for_bot_exit(self) -> None:
        if not self.process:
            return
        code = self.process.wait()
        if self._log_stream:
            try:
                self._log_stream.flush()
            except Exception:
                pass
        if not self._exiting and self.root:
            self.root.after(0, lambda: self._set_status(f"机器人已停止，退出码 {code}。可点“重新启动机器人”。"))

    def _refresh_status(self) -> None:
        if self._exiting or not self.root:
            return
        running = bool(self.process and self.process.poll() is None)
        pid = self.process.pid if running and self.process else "-"
        service_running = bool(self.service_process and self.service_process.poll() is None)
        service_pid = self.service_process.pid if service_running and self.service_process else "-"
        status = "运行中" if running else "已停止"
        service_status = "运行中" if service_running else "已停止"
        self._set_status(
            f"机器人：{status} PID {pid} | OCR 服务：{service_status} PID {service_pid}\n"
            f"模式：{self.mode} | {self.warmup_status}"
        )
        self._refresh_log_tail()
        self.root.after(2500, self._refresh_status)

    def _refresh_log_tail(self) -> None:
        if not self.log_text:
            return
        text = _read_tail(self.tray_log_file, limit=5000)
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", text)
        self.log_text.see("end")

    def _set_status(self, text: str) -> None:
        if self.status_var:
            self.status_var.set(text)

    def _exit_app(self) -> None:
        self._exiting = True
        self._set_status("正在退出...")
        self._stop_icon()
        self._stop_bot()
        self._stop_service()
        if self.root:
            self.root.destroy()

    def _stop_icon(self) -> None:
        if not self.icon:
            return
        try:
            self.icon.stop()
        except Exception as exc:
            _write_log(self.tray_log_file, f"stop icon failed: {exc}\n")
        self.icon = None

    def _notify(self, title: str, message: str) -> None:
        if self.icon and hasattr(self.icon, "notify"):
            try:
                self.icon.notify(message, title)
                return
            except Exception as exc:
                _write_log(self.tray_log_file, f"notify failed: {exc}\n")


def _timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_tail(path: Path, *, limit: int) -> str:
    try:
        if not path.exists():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-limit:]
    except Exception as exc:
        return f"读取日志失败：{exc}"


def _write_log(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log(path)
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(text)
    except Exception:
        pass


def _rotate_log(path: Path, *, max_bytes: int = 5 * 1024 * 1024, backups: int = 3) -> None:
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_suffix(path.suffix + f".{backups}")
        if oldest.exists():
            oldest.unlink()
        for index in range(backups - 1, 0, -1):
            source = path.with_suffix(path.suffix + f".{index}")
            if source.exists():
                source.replace(path.with_suffix(path.suffix + f".{index + 1}"))
        path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass


def _message_box(title: str, message: str) -> None:
    if os.name != "nt":
        print(f"{title}: {message}")
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0)
    except Exception:
        print(f"{title}: {message}")


def acquire_single_instance() -> bool:
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return True
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_NAME)
    if not handle:
        return False
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return False
    _INSTANCE_MUTEX = handle
    return True


def _find_free_port(host: str, start_port: int) -> int:
    for port in range(start_port, start_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free OCR service port in range {start_port}-{start_port + 19}")


def _service_is_ready(service_url: str) -> bool:
    try:
        with urlopen(f"{service_url}/api/v1/health", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except Exception:
        return False


def _post_service_json(url: str, payload: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"OCR service request failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("ok") is False:
        raise RuntimeError(str(result.get("error") if isinstance(result, dict) else result))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
