from __future__ import annotations

from enum import Enum
from typing import Optional, Set, List, Dict, Any

from telegram import Bot as TBot, Update
from telegram import Chat as TChat
from telegram import Message, TelegramError

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


class Chat:
    def __init__(self, _id: str, bot: TBot):
        self.logger = create_logger("chat_{}".format(_id))
        self.logger.debug("Create chat")
        self.pinned_message_id: Optional[int] = None
        self.id: str = _id
        self.bot: TBot = bot
        self.users: Set[User] = set()
        self.title: Optional[str] = None
        self.type = ChatType.UNDEFINED
        self.invite_link: Optional[str] = None

    def get_user_by_id(self, _id: int) -> Optional[User]:
        result = next(filter(lambda user: user.id == _id, self.users), None)

        return result

    def serialize(self) -> Dict[str, Any]:
        serialized = {
            "id": self.id,
            "pinned_message_id": self.pinned_message_id,
            "users": [user.serialize() for user in self.users],
            "title": self.title,
            "invite_link": self.invite_link
        }

        return serialized

    def add_user(self, user: User):
        self.users.add(user)

    @classmethod
    def deserialize(cls, json_object: Dict, bot: TBot) -> Chat:
        chat = Chat(
            json_object["id"],
            bot
        )
        chat.pinned_message_id = json_object.get("pinned_message_id")
        chat.users = {User.deserialize(user_json_object) for user_json_object in json_object.get("users", [])}
        chat.title = json_object.get("title", None)
        chat.invite_link = json_object.get("invite_link", None)

        return chat

    @group
    def pin_message(self, message_id: int, disable_notifications: bool = True, unpin: bool = False) -> bool:
        if unpin:
            self.logger.debug("Force unpin before pinning")
            self.unpin_message()

        successful_pin = False
        try:
            successful_pin = self.bot.pin_chat_message(chat_id=self.id,
                                                       message_id=message_id,
                                                       disable_notification=disable_notifications)
        except TelegramError as e:
            self.logger.error(f"Couldn't pin message due to error: {e}")

        if successful_pin:
            self.pinned_message_id = message_id
            self.logger.debug("Successfully pinned message: {}".format(message_id))
            return True
        else:
            self.logger.warning("Pinning message failed")

        return successful_pin

    @group
    def unpin_message(self) -> bool:
        successful_unpin = False
        try:
            successful_unpin = self.bot.unpin_chat_message(chat_id=self.id)
        except TelegramError as e:
            self.logger.error(f"Couldn't unpin message due to error: {e}")

        if successful_unpin:
            self.logger.info("Successfully unpinned message")
            self.pinned_message_id = None
        else:
            self.logger.info("Failed to unpin message")

        return successful_unpin

    def _send_message(self, **kwargs) -> Message:
        """
        Alias for `self.bot.send_message(chat_id=self.id, [...])`
        :param kwargs: Dict[str, Any] Passed to bot.send_message
        :raises: TelegramError Raises TelegramError if the message couldn't be sent
        :return:
        """
        message = " | ".join(["{}: {}".format(key, val) for key, val in kwargs.items()])
        self.logger.info(f"Send message with: {message}")

        result = self.bot.send_message(chat_id=self.id, **kwargs)

        self.logger.info("Result of sending message: {}".format(result))
        return result

    @group
    def administrators(self) -> Set[User]:
        """
        Lists all administrators in this chat.
        Skips administrators who are not in `self.users`.
        This doesn't work in private chats, since there are no admins in a private chat

        :return: Administrators in this chat Set[User]
        """
        administrators: Set[User] = set()

        try:
            chat_administrators = self.bot.get_chat_administrators(chat_id=self.id)
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
        user = self.get_user_by_id(update.effective_user.id)

        user.messages.add(update.effective_message)

    def messages(self) -> List[Message]:
        messages = []
        for user in self.users:
            messages.extend(user.messages)

        return messages

    def __repr__(self) -> str:
        return f"<{self.id} | {self.title}>"
