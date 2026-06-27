from __future__ import annotations

from typing import Any

from . import __version__
from . import api


try:
    from fastapi import FastAPI
except Exception:  # pragma: no cover - optional dependency
    FastAPI = None  # type: ignore


def create_app():
    if FastAPI is None:  # pragma: no cover - optional dependency
        raise RuntimeError("FastAPI is not installed. Use 'python orc-calc.py serve' or install requirements-api.txt.")

    app = FastAPI(title="废纸 OCR 计算器 API", version=__version__)

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return api.health()

    @app.get("/api/v1/templates")
    def templates() -> dict[str, Any]:
        return api.templates()

    @app.get("/api/v1/cloud-check")
    def cloud_check() -> dict[str, Any]:
        return api.cloud_check()

    @app.post("/api/v1/recognize")
    def recognize(payload: dict[str, Any]) -> dict[str, Any]:
        return api.recognize(payload)

    @app.post("/api/v1/warmup")
    def warmup(payload: dict[str, Any]) -> dict[str, Any]:
        return api.warmup(payload)

    @app.post("/api/v1/calculate")
    def calculate(payload: dict[str, Any]) -> dict[str, Any]:
        return api.calculate(payload)

    return app


app = create_app() if FastAPI is not None else None
