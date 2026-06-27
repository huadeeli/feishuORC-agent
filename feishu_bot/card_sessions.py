from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CardSession:
    session_id: str
    chat_id: str
    source_message_id: str
    card_message_id: str
    image_path: str
    note_text: str
    created_at: float


class CardSessionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def create(
        self,
        *,
        chat_id: str,
        source_message_id: str,
        image_path: Path,
        note_text: str,
    ) -> CardSession:
        session = CardSession(
            session_id=uuid.uuid4().hex,
            chat_id=chat_id,
            source_message_id=source_message_id,
            card_message_id="",
            image_path=str(image_path),
            note_text=note_text,
            created_at=time.time(),
        )
        self.save(session)
        return session

    def save(self, session: CardSession) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(session.session_id).write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> CardSession:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(session_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid card session: {session_id}")
        return CardSession(
            session_id=str(data.get("session_id") or ""),
            chat_id=str(data.get("chat_id") or ""),
            source_message_id=str(data.get("source_message_id") or ""),
            card_message_id=str(data.get("card_message_id") or ""),
            image_path=str(data.get("image_path") or ""),
            note_text=str(data.get("note_text") or ""),
            created_at=float(data.get("created_at") or 0),
        )

    def with_card_message_id(self, session: CardSession, card_message_id: str) -> CardSession:
        updated = replace(session, card_message_id=card_message_id)
        self.save(updated)
        return updated

    def _path(self, session_id: str) -> Path:
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in ("-", "_"))
        if not safe:
            raise ValueError("Card session id is empty.")
        return self.directory / f"{safe}.json"


def extract_sent_message_id(response: dict[str, Any]) -> str:
    data = response.get("data")
    if isinstance(data, dict):
        return str(data.get("message_id") or data.get("messageId") or "")
    return ""
