from __future__ import annotations

from typing import Any

from telegram import Message
from telegram import User as TUser


class User:
    def __init__(self, name: str, _id: int, chat_user: TUser | None = None):
        self.name = name
        self.id = _id
        self._internal = chat_user
        self.muted = False
        self.messages: set[Message] = set()

    def __eq__(self, other) -> bool:
        if not isinstance(other, User):
            return False

        return other.id == self.id

    def __hash__(self) -> int:
        return self.name.__hash__()

    def __str__(self) -> str:
        return f"<{' | '.join([self.name])}>"

    @classmethod
    def from_tuser(cls, chat_user: TUser) -> User:
        user = User(chat_user.first_name, chat_user.id, chat_user)

        return user

    @classmethod
    def deserialize(cls, json: dict[str, Any]) -> User:
        user = User(json.get("name"), json.get("id"))  # type: ignore
        user.muted = json.get("muted", False)

        return user

    def serialize(self) -> dict[str, Any]:
        return {"name": self.name, "muted": self.muted, "id": self.id}
