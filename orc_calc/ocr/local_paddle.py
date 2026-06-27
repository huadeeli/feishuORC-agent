from __future__ import annotations

import atexit
import os
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from orc_calc.core.image_meta import jpeg_size
from orc_calc.core.recognizer import OCRLine
from orc_calc.core.templates import find_template_by_hint

from .base import OCRProvider, OCRProviderResult


MODEL_CHECK_TIMEOUT_SECONDS = 600
RECOGNIZE_TIMEOUT_SECONDS = 600
_MODEL_STATUS_CACHE: dict[str, Any] | None = None
_MODEL_STATUS_CACHE_KEY: tuple[str, str] | None = None
_WORKERS: dict[tuple[str, str, str], "_ExternalPaddleWorker"] = {}
_WORKERS_LOCK = threading.Lock()


class LocalPaddleOCRProvider(OCRProvider):
    name = "local-paddleocr"

    def __init__(self, profile: str = "standard") -> None:
        self.profile = profile
        self._engine: Any | None = None
        self._load_error: str | None = None

    def _get_engine(self) -> Any | None:
        if self._engine is not None or self._load_error is not None:
            return self._engine
        _configure_paddle_cache()
        _add_external_ocr_runtime()
        _patch_paddle_inference_memory_optim()
        try:
            from paddleocr import PaddleOCR  # type: ignore

            try:
                self._engine = PaddleOCR(
                    lang="ch",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                )
            except TypeError:
                self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        except Exception as exc:  # pragma: no cover - optional dependency path
            self._load_error = str(exc)
            self._engine = None
        return self._engine

    def recognize(self, image_path: str | Path, *, image_filename: str | None = None) -> OCRProviderResult:
        path = Path(image_path)
        metadata = {
            "mode": "local-fast" if self.profile == "fast" else "local",
            "profile": self.profile,
            "model": "PP-OCRv5_mobile" if self.profile == "fast" else "PP-OCRv5_server",
        }
        disable_local_ocr = os.environ.get("ORC_CALC_DISABLE_LOCAL_OCR") == "1"
        if disable_local_ocr:
            self._load_error = "ORC_CALC_DISABLE_LOCAL_OCR=1"

        if not disable_local_ocr:
            runtime_root = _find_ocr_runtime_root()
            if runtime_root:
                try:
                    return OCRProviderResult(
                        self.name,
                        _recognize_with_external_runtime(runtime_root, path, profile=self.profile),
                        [],
                        metadata,
                    )
                except Exception as exc:  # pragma: no cover - frozen executable path
                    self._load_error = str(exc)

        engine = None if disable_local_ocr else self._get_engine()
        if engine is not None:
            try:
                if hasattr(engine, "predict"):
                    raw = engine.predict(str(path))
                else:
                    raw = engine.ocr(str(path), cls=True)
                return OCRProviderResult(self.name, _flatten_paddle_result(raw), [], metadata)
            except Exception as exc:  # pragma: no cover - optional dependency path
                return OCRProviderResult(self.name, [], [f"本地 PaddleOCR 调用失败: {exc}"], metadata)

        size = None
        try:
            size = jpeg_size(path)
        except OSError:
            size = None
        template = find_template_by_hint(image_filename or path.name, size)
        if template:
            load_hint = f"加载错误: {_friendly_ocr_error(self._load_error)}" if self._load_error else "未加载到 paddleocr"
            return OCRProviderResult(
                self.name,
                [],
                [f"本地 PaddleOCR 不可用，当前使用内置样图回退识别。{load_hint}"],
                metadata,
            )

        load_hint = f"加载错误: {_friendly_ocr_error(self._load_error)}" if self._load_error else "未加载到 paddleocr"
        return OCRProviderResult(
            self.name,
            [],
            [f"本地 PaddleOCR 不可用，真实上传图片无法识别。{load_hint}"],
            metadata,
        )


class _ExternalPaddleWorker:
    def __init__(self, runtime_root: Path, profile: str) -> None:
        self.runtime_root = runtime_root
        self.profile = profile
        self._lock = threading.Lock()
        self._stdout_queue: queue.Queue[str] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._process = self._start_process()

    def request(self, mode: str, *args: str, timeout: int) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise RuntimeError(self._exit_detail())
            message = json.dumps({"mode": mode, "args": list(args)}, ensure_ascii=False)
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(message + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(self._exit_detail()) from exc
            payload = self._read_payload(timeout)
            if payload.get("ok") is False:
                raise RuntimeError(str(payload.get("error") or "OCR worker request failed"))
            return payload

    def close(self) -> None:
        process = self._process
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def _start_process(self) -> subprocess.Popen[str]:
        python_exe = _runtime_python_exe(self.runtime_root)
        if python_exe is None:
            raise RuntimeError(f"OCR runtime missing python.exe: {self.runtime_root}")
        process = subprocess.Popen(
            [str(python_exe), "-u", "-c", _PADDLE_WORKER_CODE, "server", self.profile],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_worker_env(self.runtime_root),
            bufsize=1,
            **_subprocess_startup_kwargs(),
        )
        assert process.stdout is not None
        assert process.stderr is not None
        threading.Thread(target=self._read_stdout, args=(process.stdout,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(process.stderr,), daemon=True).start()
        return process

    def _read_stdout(self, stream: Any) -> None:
        for line in stream:
            self._stdout_queue.put(line)

    def _read_stderr(self, stream: Any) -> None:
        for line in stream:
            self._stderr_tail.append(line.rstrip())
            if len(self._stderr_tail) > 30:
                del self._stderr_tail[: len(self._stderr_tail) - 30]

    def _read_payload(self, timeout: int) -> dict[str, Any]:
        start_marker = "___ORC_JSON_START___"
        end_marker = "___ORC_JSON_END___"
        deadline = time.monotonic() + timeout
        buffer: list[str] = []
        in_payload = False
        while time.monotonic() < deadline:
            if self._process.poll() is not None and self._stdout_queue.empty():
                raise RuntimeError(self._exit_detail())
            remaining = max(0.1, deadline - time.monotonic())
            try:
                line = self._stdout_queue.get(timeout=min(0.5, remaining)).rstrip("\r\n")
            except queue.Empty:
                continue
            if line == start_marker:
                in_payload = True
                buffer = []
                continue
            if line == end_marker and in_payload:
                result = json.loads("\n".join(buffer))
                if not isinstance(result, dict):
                    raise RuntimeError("OCR worker returned invalid JSON payload")
                return result
            if in_payload:
                buffer.append(line)
        raise RuntimeError(f"OCR worker timed out after {timeout} seconds. {self._exit_detail()}")

    def _exit_detail(self) -> str:
        detail = "\n".join(self._stderr_tail).strip()
        if detail:
            return detail[-1600:]
        return f"OCR worker exited with {self._process.poll()}"


def ocr_runtime_status() -> dict[str, Any]:
    return check_ocr_model(force=False)


def check_ocr_model(*, force: bool = True) -> dict[str, Any]:
    global _MODEL_STATUS_CACHE, _MODEL_STATUS_CACHE_KEY

    runtime_root = _find_ocr_runtime_root()
    python_exe = _runtime_python_exe(runtime_root) if runtime_root else None
    site_packages = runtime_root / "Lib" / "site-packages" if runtime_root else None
    cache_root, paddlex_dir = _configure_paddle_cache()
    dependency_ready = bool(
        runtime_root
        and python_exe
        and site_packages
        and (site_packages / "paddleocr").exists()
        and (site_packages / "paddle").exists()
    )
    base_status = {
        "ocr_ready": False,
        "ocr_dependency_ready": dependency_ready,
        "ocr_model_loaded": False,
        "ocr_runtime_path": str(runtime_root) if runtime_root else "",
        "ocr_python_path": str(python_exe) if python_exe else "",
        "ocr_cache_path": str(cache_root),
        "ocr_paddlex_cache_path": str(paddlex_dir),
        "ocr_cache_writable": _is_writable_dir(cache_root),
        "ocr_status": "dependencies_found" if dependency_ready else "missing_runtime",
        "last_ocr_error": "",
        "runtime_mode": "external-worker" if dependency_ready else "missing",
        "is_frozen": bool(getattr(sys, "frozen", False)),
    }
    if not dependency_ready or runtime_root is None:
        base_status["last_ocr_error"] = "未找到可用的 .venv-ocr 本地 OCR 运行环境。"
        return base_status
    if not base_status["ocr_cache_writable"]:
        base_status["ocr_status"] = "cache_not_writable"
        base_status["last_ocr_error"] = f"OCR 缓存目录不可写：{cache_root}"
        return base_status

    cache_key = (str(runtime_root), str(cache_root))
    if not force:
        if _MODEL_STATUS_CACHE and _MODEL_STATUS_CACHE_KEY == cache_key:
            return {**base_status, **_MODEL_STATUS_CACHE}
        return {
            **base_status,
            "ocr_ready": dependency_ready,
            "ocr_status": "runtime_ready_model_not_loaded",
            "runtime_mode": "external-worker-not-started",
        }

    try:
        payload = _run_external_worker(runtime_root, "check", timeout=MODEL_CHECK_TIMEOUT_SECONDS)
        model_status = {
            "ocr_ready": bool(payload.get("model_loaded")),
            "ocr_model_loaded": bool(payload.get("model_loaded")),
            "ocr_status": "model_loaded" if payload.get("model_loaded") else "model_not_loaded",
            "runtime_mode": "external-worker-model-loaded" if payload.get("model_loaded") else "external-worker-model-error",
            "last_ocr_error": "",
            "ocr_cache_path": str(payload.get("cache_root") or cache_root),
            "ocr_paddlex_cache_path": str(payload.get("paddlex_cache") or paddlex_dir),
            "paddle_version": payload.get("paddle_version", ""),
        }
        if model_status["ocr_ready"]:
            _MODEL_STATUS_CACHE = model_status
            _MODEL_STATUS_CACHE_KEY = cache_key
        return {**base_status, **model_status}
    except Exception as exc:
        return {
            **base_status,
            "ocr_status": "model_load_failed",
            "runtime_mode": "external-worker-model-error",
            "last_ocr_error": _friendly_ocr_error(str(exc)),
        }




def _subprocess_startup_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": 0x08000000, "startupinfo": startupinfo}
def _flatten_paddle_result(raw: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []
    if not raw:
        return lines

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            rec_texts = node.get("rec_texts")
            if isinstance(rec_texts, list):
                rec_scores = node.get("rec_scores") or []
                rec_boxes = node.get("rec_boxes")
                if rec_boxes is None:
                    rec_boxes = node.get("rec_polys")
                if rec_boxes is None:
                    rec_boxes = []
                for index, text in enumerate(rec_texts):
                    score = rec_scores[index] if index < len(rec_scores) else 0.0
                    box = _normalize_box(rec_boxes[index]) if index < len(rec_boxes) else None
                    if text:
                        lines.append(OCRLine(str(text), float(score or 0.0), box))
                return
            text = node.get("text") or node.get("rec_text")
            score = node.get("score") or node.get("confidence") or node.get("rec_score") or 0.0
            box = node.get("box") or node.get("dt_polys")
            if text:
                lines.append(OCRLine(str(text), float(score or 0.0), box))
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2 and isinstance(node[1][0], str):
                box = node[0] if isinstance(node[0], list) else None
                lines.append(OCRLine(str(node[1][0]), float(node[1][1] or 0.0), box))
                return
            for item in node:
                visit(item)

    visit(raw)
    return lines


def _normalize_box(box: Any) -> Any:
    if hasattr(box, "tolist"):
        return box.tolist()
    return box


def _configure_paddle_cache() -> tuple[Path, Path]:
    cache_root = _ocr_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_root = _windows_short_path(cache_root)
    home_dir = cache_root / "home"
    paddlex_dir = cache_root / "paddlex"
    paddle_home = cache_root / "paddle"
    xdg_cache = cache_root / "xdg"
    for directory in (cache_root, home_dir, paddlex_dir, paddle_home, xdg_cache):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ["ORC_CALC_OCR_CACHE_DIR"] = str(cache_root)
    os.environ["HOME"] = str(home_dir)
    os.environ["USERPROFILE"] = str(home_dir)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_dir)
    os.environ["PADDLE_HOME"] = str(paddle_home)
    os.environ["PADDLEOCR_HOME"] = str(cache_root / "paddleocr")
    os.environ["XDG_CACHE_HOME"] = str(xdg_cache)
    return cache_root, paddlex_dir


def _ocr_cache_root() -> Path:
    configured = os.environ.get("ORC_CALC_OCR_CACHE_DIR")
    if configured:
        configured_path = Path(configured).expanduser().resolve()
        if _is_ascii_path(configured_path):
            return configured_path
        fallback = _ascii_cache_fallback(configured_path)
        if fallback:
            return fallback
        return configured_path

    preferred = (_application_root() / ("ocr_cache" if getattr(sys, "frozen", False) else ".ocr-cache")).resolve()
    if _is_ascii_path(preferred):
        return preferred
    fallback = _ascii_cache_fallback(preferred)
    if fallback:
        _seed_cache_from_bundled(preferred, fallback)
        return fallback
    return preferred


def _application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _windows_short_path(path: Path) -> Path:
    if os.name != "nt":
        return path
    try:
        import ctypes

        buffer_size = 32768
        buffer = ctypes.create_unicode_buffer(buffer_size)
        result = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, buffer_size)
        if result:
            return Path(buffer.value)
    except Exception:
        return path
    return path


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _ascii_cache_fallback(reference: Path) -> Path | None:
    candidates: list[Path] = []
    for env_name in ("LOCALAPPDATA", "TEMP"):
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        env_path = _windows_short_path(Path(env_value).expanduser())
        candidates.append(env_path / "orc_calc_ocr_cache")

    for parent in reference.parents:
        if _is_ascii_path(parent):
            candidates.append(parent / "orc_calc_ocr_cache")
            break

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if _is_ascii_path(candidate) and _is_writable_dir(candidate):
            return candidate.resolve()
    return None


def _seed_cache_from_bundled(bundled_cache: Path, target_cache: Path) -> None:
    if not bundled_cache.exists() or _has_ocr_model_cache(target_cache) or not _has_ocr_model_cache(bundled_cache):
        return
    try:
        target_cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundled_cache, target_cache, dirs_exist_ok=True)
    except OSError:
        return


def _has_ocr_model_cache(cache_root: Path) -> bool:
    models = cache_root / "paddlex" / "official_models"
    return all(
        (models / name / "inference.yml").exists()
        for name in ("PP-OCRv5_server_det", "PP-OCRv5_server_rec")
    )


def _patch_paddle_inference_memory_optim() -> None:
    try:
        import paddle.inference as paddle_inference  # type: ignore

        paddle_inference.Config.enable_memory_optim = lambda self, *args, **kwargs: None
    except Exception:
        return


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _friendly_ocr_error(message: str) -> str:
    detail = (message or "").strip()
    if "PermissionError" in detail or "Permission denied" in detail or "WinError 5" in detail:
        return f"本地 OCR 模型缓存权限错误：{detail}"
    if "timed out" in detail.lower() or "timeout" in detail.lower():
        return f"本地 OCR 模型加载超时：{detail}"
    return detail


def _add_external_ocr_runtime() -> None:
    root = _find_ocr_runtime_root()
    if root is not None:
        site_packages = root / "Lib" / "site-packages"
        site_packages_text = str(site_packages)
        if site_packages_text not in sys.path:
            sys.path.insert(0, site_packages_text)
        for dll_dir in (
            root,
            root / "Scripts",
            site_packages / "paddle" / "libs",
            site_packages / "paddle" / "base",
        ):
            if not dll_dir.exists():
                continue
            dll_text = str(dll_dir)
            os.environ["PATH"] = dll_text + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(dll_text)


def _find_ocr_runtime_root() -> Path | None:
    for root in _ocr_runtime_roots():
        if (root / "Lib" / "site-packages" / "paddleocr").exists():
            return root
    return None


def _runtime_python_exe(runtime_root: Path) -> Path | None:
    for candidate in (runtime_root / "python.exe", runtime_root / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return None


def _ocr_runtime_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("ORC_CALC_OCR_RUNTIME_DIR", "").strip()
    if configured:
        roots.append(Path(configured).expanduser().resolve())
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.extend([exe_dir / ".venv-ocr", exe_dir / "ocr-runtime", exe_dir.parent.parent / ".venv-ocr"])
    try:
        roots.append(Path(__file__).resolve().parents[2] / ".venv-ocr")
    except IndexError:
        pass

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique_roots.append(root)
    return unique_roots


def _recognize_with_external_runtime(runtime_root: Path, image_path: Path, *, profile: str = "standard") -> list[OCRLine]:
    payload = _run_external_worker(runtime_root, "recognize", str(image_path), timeout=RECOGNIZE_TIMEOUT_SECONDS, profile=profile)
    rows = payload.get("lines") or []
    return [OCRLine(str(row["text"]), float(row.get("confidence") or 0.0), row.get("box")) for row in rows if row.get("text")]


def _run_external_worker(runtime_root: Path, mode: str, *args: str, timeout: int, profile: str = "standard") -> dict[str, Any]:
    if os.environ.get("ORC_CALC_DISABLE_PERSISTENT_OCR") != "1":
        return _get_persistent_worker(runtime_root, profile).request(mode, *args, timeout=timeout)
    return _run_one_shot_worker(runtime_root, mode, *args, timeout=timeout, profile=profile)


def _get_persistent_worker(runtime_root: Path, profile: str) -> _ExternalPaddleWorker:
    cache_root, _ = _configure_paddle_cache()
    key = (str(runtime_root), str(cache_root), profile)
    with _WORKERS_LOCK:
        worker = _WORKERS.get(key)
        if worker is None or not worker.alive:
            worker = _ExternalPaddleWorker(runtime_root, profile)
            _WORKERS[key] = worker
        return worker


def _close_workers() -> None:
    with _WORKERS_LOCK:
        workers = list(_WORKERS.values())
        _WORKERS.clear()
    for worker in workers:
        worker.close()


atexit.register(_close_workers)


def _run_one_shot_worker(runtime_root: Path, mode: str, *args: str, timeout: int, profile: str = "standard") -> dict[str, Any]:
    python_exe = _runtime_python_exe(runtime_root)
    if python_exe is None:
        raise RuntimeError(f"OCR runtime missing python.exe: {runtime_root}")

    env = _worker_env(runtime_root)
    command = [str(python_exe), "-c", _PADDLE_WORKER_CODE, mode, profile, *args]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            check=False,
            **_subprocess_startup_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        detail = "\n".join(part for part in [str(exc), exc.stderr or "", exc.stdout or ""] if part).strip()
        raise RuntimeError(detail or f"OCR worker timed out after {timeout} seconds") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-1600:]
        raise RuntimeError(detail or f"OCR worker exited with {completed.returncode}")

    output = completed.stdout
    start_marker = "___ORC_JSON_START___"
    end_marker = "___ORC_JSON_END___"
    if start_marker not in output or end_marker not in output:
        raise RuntimeError((completed.stderr or output or "OCR worker returned no JSON").strip()[-1600:])
    payload = output.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise RuntimeError("OCR worker returned invalid JSON payload")
    return result


def _worker_env(runtime_root: Path) -> dict[str, str]:
    cache_root, paddlex_dir = _configure_paddle_cache()
    home_dir = cache_root / "home"
    paddle_home = cache_root / "paddle"
    xdg_cache = cache_root / "xdg"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    env["ORC_CALC_OCR_CACHE_DIR"] = str(cache_root)
    env["HOME"] = str(home_dir)
    env["USERPROFILE"] = str(home_dir)
    env["PADDLE_PDX_CACHE_HOME"] = str(paddlex_dir)
    env["PADDLE_HOME"] = str(paddle_home)
    env["PADDLEOCR_HOME"] = str(cache_root / "paddleocr")
    env["XDG_CACHE_HOME"] = str(xdg_cache)
    env["FLAGS_use_mkldnn"] = "0"
    env["FLAGS_use_onednn"] = "0"
    path_parts = [str(runtime_root)]
    scripts_dir = runtime_root / "Scripts"
    if scripts_dir.exists():
        path_parts.append(str(scripts_dir))
    env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])
    return env


_PADDLE_WORKER_CODE = r"""
import json
import os
import sys
import traceback
from pathlib import Path

real_stdout = sys.stdout
sys.stdout = sys.stderr

cache_root = Path(os.environ.get("ORC_CALC_OCR_CACHE_DIR") or Path.cwd() / "ocr_cache")
home_dir = cache_root / "home"
paddlex_dir = cache_root / "paddlex"
paddle_home = cache_root / "paddle"
xdg_cache = cache_root / "xdg"
for directory in (cache_root, home_dir, paddlex_dir, paddle_home, xdg_cache):
    directory.mkdir(parents=True, exist_ok=True)
os.environ["ORC_CALC_OCR_CACHE_DIR"] = str(cache_root)
os.environ["HOME"] = str(home_dir)
os.environ["USERPROFILE"] = str(home_dir)
os.environ["PADDLE_PDX_CACHE_HOME"] = str(paddlex_dir)
os.environ["PADDLE_HOME"] = str(paddle_home)
os.environ["PADDLEOCR_HOME"] = str(cache_root / "paddleocr")
os.environ["XDG_CACHE_HOME"] = str(xdg_cache)
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"

try:
    import paddle.inference as paddle_inference
    paddle_inference.Config.enable_memory_optim = lambda self, *args, **kwargs: None
except Exception:
    pass

from paddleocr import PaddleOCR

try:
    import paddle
    paddle_version = getattr(paddle, "__version__", "")
except Exception:
    paddle_version = ""

def create_engine(profile):
    kwargs = {
        "lang": "ch",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": True,
        "enable_mkldnn": False,
    }
    if profile == "fast":
        kwargs["text_detection_model_name"] = "PP-OCRv5_mobile_det"
        kwargs["text_recognition_model_name"] = "PP-OCRv5_mobile_rec"
    try:
        return PaddleOCR(**kwargs)
    except TypeError:
        return PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)

def write_payload(payload):
    real_stdout.write("___ORC_JSON_START___\n")
    real_stdout.write(json.dumps(payload, ensure_ascii=False))
    real_stdout.write("\n___ORC_JSON_END___\n")
    real_stdout.flush()

def check_payload():
    return {
        "model_loaded": True,
        "cache_root": str(cache_root),
        "paddlex_cache": str(paddlex_dir),
        "paddle_version": paddle_version,
        "profile": profile,
    }

def recognize_payload(image_path):
    raw = engine.predict(image_path) if hasattr(engine, "predict") else engine.ocr(image_path, cls=True)
    lines = []

    def normalize_box(box):
        if hasattr(box, "tolist"):
            return box.tolist()
        return box

    def visit(node):
        if isinstance(node, dict):
            rec_texts = node.get("rec_texts")
            if isinstance(rec_texts, list):
                rec_scores = node.get("rec_scores") or []
                rec_boxes = node.get("rec_boxes")
                if rec_boxes is None:
                    rec_boxes = node.get("rec_polys")
                if rec_boxes is None:
                    rec_boxes = []
                for index, text in enumerate(rec_texts):
                    score = rec_scores[index] if index < len(rec_scores) else 0.0
                    box = normalize_box(rec_boxes[index]) if index < len(rec_boxes) else None
                    if text:
                        lines.append({"text": str(text), "confidence": float(score or 0.0), "box": box})
                return
            text = node.get("text") or node.get("rec_text")
            score = node.get("score") or node.get("confidence") or node.get("rec_score") or 0.0
            box = node.get("box") or node.get("dt_polys")
            if text:
                lines.append({"text": str(text), "confidence": float(score or 0.0), "box": normalize_box(box)})
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and len(node[1]) >= 2 and isinstance(node[1][0], str):
                box = node[0] if isinstance(node[0], list) else None
                lines.append({"text": str(node[1][0]), "confidence": float(node[1][1] or 0.0), "box": box})
                return
            for item in node:
                visit(item)

    visit(raw)
    payload = check_payload()
    payload["lines"] = lines
    return payload

def handle_request(mode, args):
    if mode == "check":
        return check_payload()
    if mode == "recognize":
        if not args:
            raise RuntimeError("recognize requires image path")
        return recognize_payload(args[0])
    raise RuntimeError(f"Unknown OCR worker mode: {mode}")

entry_mode = sys.argv[1] if len(sys.argv) > 1 else "recognize"
if entry_mode == "server":
    profile = sys.argv[2] if len(sys.argv) > 2 else "standard"
    engine = create_engine(profile)
    for request_line in sys.stdin:
        try:
            request = json.loads(request_line)
            payload = handle_request(str(request.get("mode") or ""), list(request.get("args") or []))
        except Exception:
            payload = {"ok": False, "error": traceback.format_exc()[-1600:]}
        write_payload(payload)
else:
    profile = sys.argv[2] if len(sys.argv) > 2 else "standard"
    engine = create_engine(profile)
    write_payload(handle_request(entry_mode, sys.argv[3:]))
"""
