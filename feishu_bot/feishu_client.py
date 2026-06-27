from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import BotConfig


class FeishuApiError(RuntimeError):
    pass


class FeishuApiClient:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self._tenant_access_token = ""
        self._token_expires_at = 0.0

    def send_text(self, chat_id: str, text: str) -> dict[str, Any]:
        content = json.dumps({"text": text}, ensure_ascii=False)
        return self._send_message(chat_id, "text", content)

    def send_interactive_card(self, chat_id: str, card: dict[str, Any]) -> dict[str, Any]:
        content = json.dumps(card, ensure_ascii=False)
        return self._send_message(chat_id, "interactive", content)

    def update_interactive_card(self, message_id: str, card: dict[str, Any]) -> dict[str, Any]:
        content = json.dumps(card, ensure_ascii=False)
        path = f"/open-apis/im/v1/messages/{urllib.parse.quote(message_id, safe='')}"
        return self._request_json(
            "PATCH",
            path,
            {"content": content},
            auth=True,
        )

    def _send_message(self, chat_id: str, msg_type: str, content: str) -> dict[str, Any]:
        path = "/open-apis/im/v1/messages"
        query = urllib.parse.urlencode({"receive_id_type": "chat_id"})
        return self._request_json(
            "POST",
            f"{path}?{query}",
            {
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": content,
            },
            auth=True,
        )

    def download_message_resource(
        self,
        *,
        message_id: str,
        file_key: str,
        resource_type: str,
        destination: Path,
    ) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        path = (
            "/open-apis/im/v1/messages/"
            f"{urllib.parse.quote(message_id, safe='')}/resources/"
            f"{urllib.parse.quote(file_key, safe='')}"
        )
        query = urllib.parse.urlencode({"type": resource_type})
        request = urllib.request.Request(
            f"{self.config.feishu_base_url}{path}?{query}",
            headers={"Authorization": f"Bearer {self._get_tenant_access_token()}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                destination.write_bytes(response.read())
                return destination
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FeishuApiError(f"Feishu resource download failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise FeishuApiError(f"Feishu resource download failed: {exc}") from exc

    def _get_tenant_access_token(self) -> str:
        if self._tenant_access_token and time.time() < self._token_expires_at - 60:
            return self._tenant_access_token

        response = self._request_json(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            auth=False,
        )
        token = str(response.get("tenant_access_token") or "")
        if not token:
            raise FeishuApiError("Feishu did not return tenant_access_token.")
        self._tenant_access_token = token
        self._token_expires_at = time.time() + int(response.get("expire", 7200))
        return token

    def _request_json(self, method: str, path_with_query: str, payload: dict[str, Any], *, auth: bool) -> dict[str, Any]:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if auth:
            headers["Authorization"] = f"Bearer {self._get_tenant_access_token()}"
        request = urllib.request.Request(
            f"{self.config.feishu_base_url}{path_with_query}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise FeishuApiError(f"Feishu API failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise FeishuApiError(f"Feishu API failed: {exc}") from exc

        code = data.get("code", 0)
        if code not in (0, "0"):
            raise FeishuApiError(f"Feishu API returned code={code}: {data.get('msg') or data}")
        return data
