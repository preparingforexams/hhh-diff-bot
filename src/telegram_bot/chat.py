from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from telegram import Bot as TBot
from telegram import Chat as TChat
from telegram import ChatPermissions, Message, Update
from telegram.error import TelegramError

from .decorators import group
from .logger import create_logger
from .user import User


class ChatType(Enum):
    UNDEFINED = ""
    PRIVATE = TChat.PRIVATE
    GROUP = TChat.GROUP
    SUPERGROUP = TChat.SUPERGROUP

    def __eq__(self, other) -> bool:
        if not isinstance(other, str):
            if isinstance(other, ChatType):
                return self.value == other.value
            else:
                return False

        return self.value == other

    def serialize(self):
        return self.value

    @staticmethod
    def deserialize(string: str):
        try:
            return ChatType(string)
        except ValueError:
            return ChatType.UNDEFINED


class Chat:
    def __init__(self, _id: str | int, bot: TBot):
        self.logger = create_logger(f"chat_{_id}")
        self.logger.debug("Create chat")
        self.pinned_message_id: int | None = None
        self.id: int = int(_id)
        self.bot: TBot = bot
        self.users: set[User] = set()
        self.title: str | None = None
        self.type = ChatType.UNDEFINED
        self.invite_link: str | None = None
        self.description: str | None = None
        self.last_chat_event_time: datetime | None = None
        self.created_message_id: int | None = None
        self.premium_users_only = False

    def get_user_by_id(self, _id: int) -> User | None:
        result = next(filter(lambda user: user.id == _id, self.users), None)

        return result

    def serialize(self) -> dict[str, Any]:
        chat_type = (
            self.type if isinstance(self.type, ChatType) else ChatType(self.type)
        )
        last_chat_event_isotime = (
            self.last_chat_event_time.isoformat() if self.last_chat_event_time else None
        )

        serialized = {
            "id": self.id,
            "pinned_message_id": self.pinned_message_id,
            "users": [user.serialize() for user in self.users],
            "title": self.title,
            "invite_link": self.invite_link,
            "description": self.description,
            "type": chat_type.serialize(),
            "last_chat_event_isotime": last_chat_event_isotime,
            "created_message_id": self.created_message_id,
            "premium_users_only": self.premium_users_only,
        }

        return serialized

    def add_user(self, user: User):
        self.users.add(user)

    @classmethod
    def deserialize(cls, json_object: dict, bot: TBot) -> Chat | None:
        try:
            chat = Chat(json_object["id"], bot)
        except (TypeError, ValueError):
            create_logger("Chat.deserialize").error("chat_id was None")
            return None
        pmi = json_object.get("pinned_message_id", "")
        chat.pinned_message_id = int(pmi) if pmi else None
        chat.users = {
            User.deserialize(user_json_object)
            for user_json_object in json_object.get("users", [])
        }
        chat.title = json_object.get("title", None)
        chat.invite_link = json_object.get("invite_link", None)
        chat.description = json_object.get("description", None)
        chat.type = ChatType.deserialize(json_object.get("type", ""))
        chat.created_message_id = json_object.get("created_message_id", None)
        if last_chat_event_time := json_object.get("last_chat_event_isotime"):
            chat.last_chat_event_time = datetime.fromisoformat(last_chat_event_time)
        chat.premium_users_only = bool(json_object.get("premium_users_only", False))

        return chat

    @group
    async def pin_message(
        self, message_id: int, disable_notifications: bool = True, unpin: bool = False
    ) -> bool:
        if unpin:
            self.logger.debug("Force unpin before pinning")
            await self.unpin_message()

        successful_pin = False
        try:
            successful_pin = await self.bot.pin_chat_message(
                chat_id=self.id,
                message_id=message_id,
                disable_notification=disable_notifications,
            )
        except TelegramError as e:
            self.logger.error(f"Couldn't pin message due to error: {e}")

        if successful_pin:
            self.pinned_message_id = message_id
            self.logger.debug(f"Successfully pinned message: {message_id}")
            return True
        else:
            self.logger.warning("Pinning message failed")

        return successful_pin

    @group
    async def unpin_message(self) -> bool:
        successful_unpin = False
        try:
            successful_unpin = await self.bot.unpin_chat_message(chat_id=self.id)
        except TelegramError as e:
            self.logger.error(f"Couldn't unpin message due to error: {e}")

        if successful_unpin:
            self.logger.info("Successfully unpinned message")
            self.pinned_message_id = None
        else:
            self.logger.info("Failed to unpin message")

        return successful_unpin

    async def _send_message(self, **kwargs) -> Message:
        """
        Alias for `self.bot.send_message(chat_id=self.id, [...])`
        :param kwargs: Dict[str, Any] Passed to bot.send_message
        :raises: TelegramError Raises TelegramError if the message couldn't be sent
        :return:
        """
        message = " | ".join([f"{key}: {val}" for key, val in kwargs.items()])
        self.logger.info(f"Send message with: {message}")

        result = await self.bot.send_message(chat_id=self.id, **kwargs)

        self.logger.info(f"Result of sending message: {result}")
        return result

    @group
    async def administrators(self) -> set[User]:
        """
        Lists all administrators in this chat.
        Skips administrators who are not in `self.users`.
        This doesn't work in private chats, since there are no admins in a private chat

        :return: Administrators in this chat Set[User]
        """
        administrators: set[User] = set()

        try:
            chat_administrators = await self.bot.get_chat_administrators(
                chat_id=self.id
            )
        except TelegramError:
            return administrators

        for admin in chat_administrators:
            try:
                # noinspection PyShadowingNames
                # no it doesn't shadow `user` from the lhs
                user = next(filter(lambda user: user.id == admin.user.id, self.users))
                administrators.add(user)
            except StopIteration:
                pass

        return administrators

    def add_message(self, update: Update) -> None:
        user = self.get_user_by_id(update.effective_user.id)  # type: ignore[union-attr]

        user.messages.add(update.effective_message)  # type: ignore[arg-type, union-attr]

    def messages(self) -> list[Message]:
        messages: list[Message] = []
        for user in self.users:
            messages.extend(user.messages)

        return messages

    def __repr__(self) -> str:
        return f"<{self.id} | {self.title}>"

    def is_group(self) -> bool:
        return self.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    def to_message_entry(self):
        try:
            if self.invite_link:
                return f'<a href="{self.invite_link}">{self.title}</a>'
            else:
                return f"{self.title}"
        except AttributeError:
            return f"{self.title}"

    async def permissions(self) -> ChatPermissions:
        chat = await self.bot.get_chat(self.id)
        if permissions := chat.permissions:
            return permissions
        raise ValueError("Missing chat.permissions despite library docs")
