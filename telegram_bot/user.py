from __future__ import annotations

from typing import Any, Dict, Optional, Set

from telegram import Message, ChatPermissions
from telegram import User as TUser

from . import chat


class User:
    def __init__(self, name: str, _id: int, chat_user: Optional[TUser] = None):
        self.name = name
        self.id = _id
        self._internal = chat_user
        self.muted = False
        self.messages: Set[Message] = set()

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
    def deserialize(cls, json: Dict[str, Any]) -> User:
        user = User(json.get("name"), json.get("id"))
        user.muted = json.get("muted", False)

        return user

    def serialize(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "muted": self.muted,
            "id": self.id
        }

    async def is_admin(self, chat: chat.Chat):
        return self in chat.administrators()

    async def can_change_info(self, bot, chat: chat.Chat, chat_permissions: ChatPermissions) -> bool:
        can_change_info = chat_permissions.can_change_info
        is_admin = await self.is_admin(chat)
        if is_admin:
            default_admin_permissions = await bot.get_my_default_administrator_rights()
            can_change_info = default_admin_permissions.can_change_info

        return can_change_info and chat.is_group()
