import json
import os
import tempfile
from datetime import datetime, timedelta
from enum import Enum
from itertools import zip_longest, groupby
from threading import Timer
from typing import Any, List, Optional, Dict, Iterable, Tuple, Set

from telegram import Update, Message, ChatPermissions
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application
from telegram.ext import CallbackContext

from .chat import Chat, User
from .decorators import Command
from .logger import create_logger
from .openai import generate_thumbnail


def grouper(iterable, n, fillvalue=None) -> Iterable[Tuple[Any, Any]]:
    """Collect data into fixed-length chunks or blocks"""
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


class SpamType(Enum):
    NONE = 0
    CONSECUTIVE = 1
    DIFFERENT = 2
    SAME = 3


class Bot:
    def __init__(self, application: Application, state_filepath: str):
        self.logger = create_logger("hhh_diff_bot")
        self.chats: Dict[int, Chat] = {}
        self.application = application
        self.main_admin_ids: Set[int] = self._load_main_admin_ids()
        self.state: Dict[str, Any] = {
            "group_message_id": [],
            "recent_changes": [],
            "hhh_id": -1001473841450,
            "pinned_message_id": None
        }
        self.state_filepath = state_filepath

    def _load_main_admin_ids(self) -> Set[int]:
        raw_value = os.getenv("MAIN_ADMIN_IDS")
        if not raw_value:
            self.logger.warning("MAIN_ADMIN_IDS is not set!")
            return set()

        try:
            id_list = json.loads(raw_value)
        except ValueError as e:
            self.logger.error("Could not load main admins", exc_info=e)
            return set()

        if not isinstance(id_list, list):
            self.logger.error("MAIN_ADMIN_IDS is not a JSON list")
            return set()

        result = set()
        for main_admin_id in id_list:
            try:
                result.add(int(main_admin_id))
            except ValueError:
                self.logger.error("Not a valid user ID: %s", main_admin_id)
        return result

    def save_state(self) -> None:
        self.state["chats"] = [chat.serialize() for chat in self.chats.values()]
        with open(self.state_filepath, "w+") as f:
            json.dump(self.state, f)

    @Command(chat_admin=True)
    async def delete_chat(self, update: Update, context: CallbackContext) -> None:
        chat: Chat = context.chat_data["chat"]

        if chat.id in self.chats:
            self.logger.info(f"Deleting chat ({chat}) from state.")
            del self.chats[chat.id]
            del context.chat_data["chat"]

    @Command(main_admin=True)
    async def delete_chat_by_id(self, update: Update, context: CallbackContext) -> Optional[Message]:
        try:
            chat_id = int(context.args[0])
        except (IndexError, ValueError):
            return await update.effective_message.reply_text(
                text=f"Enter a (valid) chat_id as an argument to use this command.")

        try:
            self.chats.pop(chat_id)
        except KeyError:
            return await update.effective_message.reply_text(text=f"Not a valid chat_id.")

    async def set_user_restriction(self, chat_id: int, user: User, until_date: timedelta, permissions: ChatPermissions,
                                   reason: str = None) -> bool:
        timestamp: int = int((datetime.now() + until_date).timestamp())
        try:
            result: bool = await self.application.bot.restrict_chat_member(chat_id, user.id, permissions,
                                                                           until_date=timestamp)
            if not permissions.can_send_messages:
                datestring: str = str(until_date).rsplit(".")[0]  # str(timedelta) -> [D day[s], ][H]H:MM:SS[.UUUUUU]
                message = f"{user.name} has been restricted for {datestring}."
                if reason:
                    message += f"\nReason: {reason}"
                await self.send_message(chat_id=chat_id, text=message, disable_notification=True)
        except TelegramError as e:
            if e.message == "Can't demote chat creator" and not permissions.can_send_messages:
                message = "Sadly, user {} couldn't be restricted due to: `{}`. Shame on {}".format(user.name,
                                                                                                   e.message,
                                                                                                   user.name)
                self.logger.debug("{}".format(message))
                await self.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
            self.logger.error(e)
            result = False

        return result

    async def unmute_user(self, chat_id: int, user: User) -> bool:
        result = False
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                      can_send_other_messages=True, can_add_web_page_previews=True)

        try:
            # if self.updater.bot.promote_chat_member(chat_id, user.id, can_post_messages=True):
            if await self.set_user_restriction(chat_id, user, timedelta(minutes=0), permissions):
                user.muted = False
                result = True
            else:
                self.logger.error("Failed to unmute user")
        except TelegramError:
            self.logger.error("Error while promoting chat member", exc_info=True)

        return result

    async def mute_user(self, chat_id: int, user: User, until_date: timedelta, reason: Optional[str] = None) -> bool:
        if user.muted:
            return True

        permissions = ChatPermissions(can_send_messages=False)
        result = False
        self.logger.info(f"Reason for muting: {reason}")
        if await self.set_user_restriction(chat_id, user, until_date=until_date, reason=reason,
                                           permissions=permissions):
            user.muted = True
            result = True

            # We'd need to parse the exception before assigning user.muted differently
            def _set_user_unmute():
                user.muted = False

            self.logger.info(f"Set timer for {until_date.total_seconds()}s to set user mute state to `False`")
            Timer(until_date.total_seconds(), _set_user_unmute).start()

        return result

    def update_recent_changes(self, update: str):
        rc: List[str] = self.state.get("recent_changes", [])
        if len(rc) > 2:
            rc.pop()

        self.state["recent_changes"] = [update] + rc

    @staticmethod
    def create_latest_change_text(chat: Chat, new_title: str, delete: bool = False) -> str:
        change = f"Added {chat.title}"
        if new_title:
            change = f"{chat.title} -> {new_title}"
        elif delete:
            change = f"Removed {chat.title}"

        return change

    def build_hhh_group_list_text(self, prefix: str = "", suffix: str = "") -> List[str]:
        """
        For now, we'll assume that chats starting with the same letter will all fit into a single message
        :param prefix: Put in front of the constructed text for the groups names
        :param suffix: Put behind of the constructed text for the groups names
        :return: List[str]
        """

        messages = []
        message = f"{prefix}\n" if prefix else ""
        """
        Telegram counts the character count after entity parsing.
        i.e. <a href="https://example.com">A</a> should only be one character
        We need this for the invite links
        """
        deductable_per_chat = 0

        for _, g in groupby(
                sorted([chat for _, chat in self.chats.items() if chat and chat.title], key=lambda c: c.title.lower()),
                key=lambda c: c.title[0].lower()):
            line = " | ".join([chat.to_message_entry() for chat in g]) + "\n"
            if len(message) + len(line) - deductable_per_chat * len(list(g)) >= 4096:
                messages.append(message)
                message = ""

            message += line

        if len(message) + len(suffix) >= 4096:
            messages.append(message)
            message = ""

        message += suffix
        messages.append(message)

        return messages

    @property
    def group_message_ids(self) -> List:
        """
        This is purely for migrative purposes (str -> list)

        :return: List[str]
        """
        value = self.state.get("group_message_id", [])
        if not value:
            return []
        elif isinstance(value, str):
            return [value]
        else:
            return value

    @group_message_ids.setter
    def group_message_ids(self, value: List[str]):
        self.state["group_message_id"] = value

    async def delete_message(self, chat_id: str, message_id: str, *args, **kwargs):
        return await self.application.bot.delete_message(chat_id=chat_id, message_id=message_id, *args, **kwargs)

    async def update_hhh_message(self, chat: Chat, new_title: str = "", delete: bool = False,
                                 create_changelog: bool = False):
        if create_changelog:
            latest_change = self.create_latest_change_text(chat, new_title, delete)
            self.logger.debug(f"Add latest change {latest_change} to recent_changes")
            self.update_recent_changes(latest_change)

        if new_title:
            self.logger.debug(f"Update chat.title ({chat.title}) to {new_title}.")
            chat.title = new_title
        self.chats.update({chat.id: chat})
        if delete and chat.id in self.chats.keys():
            self.chats.pop(chat.id)
        self.logger.debug(f"Build new group list.")

        total_group_count_text = f"{len([c for c in self.chats.values() if c.title])} groups in total"
        changes = "\n".join(["========", "\n".join(self.state["recent_changes"])])
        messages = self.build_hhh_group_list_text(prefix=total_group_count_text, suffix=changes)

        diff = len(messages) - len(self.group_message_ids)
        if diff > 0:
            # We have to send more messages than before
            # -> send a new set of messages since we can't insert one into the conversation
            self.group_message_ids = []
        elif diff < 0:
            # We have less messages than before
            # -> delete the unused ones
            for message_id in self.group_message_ids[-diff:]:
                try:
                    await self.delete_message(self.state["hhh_id"], message_id)
                except BadRequest as e:
                    self.logger.debug("Exception occured", exc_info=True)

        pinned = False
        for index, message_text in enumerate(messages):
            if not self.group_message_ids or index >= len(self.group_message_ids):
                self.logger.debug(f"Send {len(messages)} new messages.")
                message: Message = await self.send_message(chat_id=self.state["hhh_id"], text=message_text,
                                                           parse_mode=ParseMode.HTML)
                self.group_message_ids = self.group_message_ids + [message.message_id]

                if not pinned:
                    try:
                        if self.state.get("pinned_message_id"):
                            try:
                                await self.application.bot.unpin_chat_message(chat_id=self.state["hhh_id"],
                                                                              message_id=self.state[
                                                                                  "pinned_message_id"])
                            except BadRequest:
                                self.logger.error("Couldn't unpin message", exc_info=True)

                        await self.application.bot.pin_chat_message(chat_id=self.state["hhh_id"],
                                                                    message_id=self.group_message_ids[0],
                                                                    disable_notification=True)

                        self.state["pinned_message_id"] = self.group_message_ids[0]
                        pinned = True
                    except BadRequest:
                        self.logger.error("Couldn't pin the message", exc_info=True)
                        pass
            else:
                try:
                    self.logger.debug(f"Edit an old message with the new text ({message_text})")
                    await self.application.bot.edit_message_text(message_text, chat_id=self.state["hhh_id"],
                                                                 message_id=self.group_message_ids[index],
                                                                 disable_web_page_preview=True,
                                                                 parse_mode=ParseMode.HTML)
                except BadRequest as e:
                    self.logger.exception("Couldn't edit message", exc_info=True)
                    if e.message == "Message to edit not found":
                        self.logger.debug("Try sending a new message")
                        self.group_message_ids = []
                        return await self.update_hhh_message(chat, new_title=new_title, delete=delete,
                                                             create_changelog=False)

    @Command()
    async def handle_left_chat_member(self, update: Update, context: CallbackContext) -> None:
        chat: Chat = context.chat_data["chat"]

        if update.effective_message.left_chat_member.id != self.application.bot.id:
            try:
                user: User = [user for user in chat.users if user.id == update.effective_message.left_chat_member.id][0]
            except IndexError:
                self.logger.error("Couldn't find user in chat")
            else:
                chat.users.remove(user)
        else:
            await self.update_hhh_message(chat, delete=True, create_changelog=True)
            context.chat_data.clear()

    def set_state(self, state: Dict[str, Any]) -> None:
        self.state = state
        self.chats = {schat["id"]: Chat.deserialize(schat, self.application.bot) for schat in state.get("chats", [])}

    async def send_message(self, *, chat_id: int, text: str, **kwargs) -> Message:
        return await self.application.bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True,
                                                       **kwargs)

    def _get_chat_by_title(self, title: str) -> Optional[Chat]:
        for chat in self.chats.values():
            if title == chat.title:
                return chat

        return None

    @Command()
    async def show_users(self, update: Update, context: CallbackContext) -> Optional[Message]:
        from_chat: Chat = context.chat_data["chat"]
        if context.args:
            search_title = " ".join(context.args).strip()
            chat: Optional[Chat] = self._get_chat_by_title(search_title)
            if not chat:
                return await self.send_message(chat_id=from_chat.id, text="This chat doesn't exist")
        else:
            chat = from_chat

        sorted_users: List[User] = sorted(chat.users, key=lambda _user: _user.name)
        if sorted_users:
            message = "\n".join([user.name for user in sorted_users])
        else:
            message = "No active users. Users need to write a message in the chat to be recognized (not just a command)"

        return await self.send_message(chat_id=from_chat.id, text=message)

    async def send_created_message(self, update: Update, context: CallbackContext) -> Message:
        chat: Chat = context.chat_data["chat"]

        message = await self.send_message(chat_id=self.state["hhh_id"], text=f"Created {update.effective_chat.title}")
        chat.created_message_id = message.message_id

        return message

    @Command()
    async def new_member(self, update: Update, context: CallbackContext) -> None:
        chat = context.chat_data["chat"]

        self.logger.info(f"New member(s) have joined this chat")

        for member in update.effective_message.new_chat_members:
            if member.id != self.application.bot.id:
                chat.users.add(User.from_tuser(member))
            else:
                try:
                    await self.update_hhh_message(context.chat_data["chat"], create_changelog=True)
                except BadRequest:
                    self.logger.exception("Failed to update message", exc_info=True)

                await self.send_created_message(update, context)

    @Command()
    async def status(self, update: Update, context: CallbackContext):
        return await update.effective_message.reply_text(text=f"{context.chat_data['chat']}")

    @Command()
    async def version(self, update: Update, context: CallbackContext):
        version = os.getenv("APP_VERSION", "unknown")
        return await update.effective_message.reply_text(version)

    @Command()
    async def server_time(self, update: Update, context: CallbackContext):
        return await update.effective_message.reply_text(datetime.now().strftime("%d-%m-%Y %H-%M-%S"))

    @Command()
    async def get_data(self, update: Update, context: CallbackContext) -> Message:
        chat: Chat = context.chat_data["chat"]
        data = [_chat for _chat in self.state.get("chats", []) if _chat.get("id") == chat.id]

        if data:
            with tempfile.TemporaryFile() as temp:
                temp.write(json.dumps(data[0]).encode("utf-8"))
                temp.seek(0)
                return await self.application.bot.send_document(chat_id=chat.id, document=temp,
                                                                filename=f"{chat.title}.json")
        else:
            return await update.effective_message.reply_text("Couldn't find any data for this chat.")

    @Command(chat_admin=True)
    async def mute(self, update: Update, context: CallbackContext):
        if not context.args:
            message = "Please provide a user and an optional timeout (`/mute <user> [<timeout in minutes>] [<reason>]`)"
            self.logger.warning("No arguments have been provided, don't execute `mute`.")
            return await self.send_message(chat_id=update.message.chat_id, text=message, parse_mode=ParseMode.MARKDOWN)

        username = context.args[0]
        minutes = 15
        reason = " ".join(context.args[2:])

        try:
            minutes = int(context.args[1])
        except (IndexError, ValueError):
            self.logger.error("Exception while getting time string from mute command", exc_info=True)

        mute_time = timedelta(minutes=minutes)
        chat = context.chat_data["chat"]

        try:
            user = next(filter(lambda x: x.name == username, chat.users))
        except StopIteration:
            self.logger.warning(f"Couldn't find user {username} in users for chat {update.message.chat_id}",
                                exc_info=True)
            return await update.effective_message.reply_text(f"Can't mute {username} (not found in current chat).")
        else:
            return await self.mute_user(update.message.chat_id, user, until_date=mute_time, reason=reason)

    @Command(chat_admin=True)
    async def unmute(self, update: Update, context: CallbackContext):
        if not context.args:
            message = "You have to provide a user which should be unmuted."
            self.logger.warning("No arguments have been provided, don't execute `unmute`.")
            return await update.effective_message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        username: str = context.args[0].strip()
        chat: Chat = context.chat_data["chat"]

        # @all is an unusable username
        if username == "@all":
            for user in chat.users:
                try:
                    await self.unmute_user(chat.id, user)
                except BadRequest:
                    self.logger.error(f"Failed to unmute user ({user})")

            return

        try:
            user = next(filter(lambda x: x.name.lower() == username.lower(), chat.users))
        except StopIteration:
            self.logger.warning(f"Couldn't find user {username} in users for chat {update.message.chat_id}",
                                exc_info=True)
            return await update.effective_message.reply_text(f"Can't unmute {username} (not found in current chat).")
        else:
            if self.unmute_user(chat.id, user):
                return await update.effective_message.reply_text(f"Successfully unmuted {username}.")
            else:
                return await update.effective_message.reply_text(f"Failed to unmute {username}.")

    async def kick_user(self, chat: Chat, user_id: int):
        # since we only want to kick the user we can unban them immediately after, since we don't want to ensure
        # unbanning by calling `unban_chat_member` we simply provide a small ban time
        # Note: "If user is banned for more than 366 days or less than 30 seconds
        #        from the current time they are considered to be banned forever."
        ban_until = datetime.now() + timedelta(minutes=1)
        return await self.application.bot.ban_chat_member(chat_id=chat.id, user_id=user_id, until_date=ban_until)

    @Command(chat_admin=True)
    async def kick(self, update: Update, context: CallbackContext):
        chat: Chat = context.chat_data["chat"]

        if not context.args:
            message = "Please provide a user and an optional reason(`/kick <user> [<reason>]`)"
            self.logger.warning("No arguments have been provided, don't execute `kick`.")
            return await update.message.reply_text(text=message, parse_mode=ParseMode.MARKDOWN)

        username = context.args[0]
        reason = " ".join(context.args[1:])

        try:
            user: User = next(filter(lambda x: x.name == username, chat.users))
        except StopIteration:
            self.logger.warning(f"Couldn't find user {username} in users for chat {update.message.chat_id}",
                                exc_info=True)
            return await update.effective_message.reply_text(f"Can't kick {username} (not found in current chat).")
        else:
            try:
                result = await self.kick_user(chat, user.id)
            except TelegramError as e:
                message = f"Couldn't remove {user.name} from chat due to error ({e})"
                self.logger.error(message)
                return await update.message.reply_text(message)
            else:
                if result:
                    message = f"{user.name} was kicked from chat"
                    message += f" due to {reason}." if reason else "."
                    self.logger.debug(message)
                    chat.users.remove(user)
                    return await update.message.reply_text(message)
                else:
                    message = f"{user.name} couldn't be kicked from chat"
                    self.logger.warning(message)
                    return await update.effective_message.reply_text(message)

    @Command()
    async def new_chat_title(self, update: Update, context: CallbackContext):
        chat: Chat = context.chat_data["chat"]
        new_title = update.effective_message.new_chat_title

        return await self.update_hhh_message(chat, new_title=new_title, create_changelog=True)

    @Command()
    async def chat_created(self, update: Update, context: CallbackContext):
        try:
            await self.update_hhh_message(context.chat_data["chat"], create_changelog=True)
        except BadRequest:
            self.logger.exception("Failed to update message", exc_info=True)

        return await self.send_created_message(update, context)

    @Command(chat_admin=True)
    async def add_invite_link(self, update: Update, context: CallbackContext):
        chat: Chat = context.chat_data["chat"]
        if context.args:
            invite_link: str = context.args[0]
        else:
            return await update.effective_message.reply_text("Provide an invite link moron")

        if _validate_invite_link(invite_link):
            chat.invite_link = invite_link

            if await update.effective_message.reply_text("Added (new) invite link"):
                await self.update_hhh_message(context.chat_data["chat"])

            if chat.created_message_id:
                text = f"Created {chat.to_message_entry()}"
                return await self.application.bot.edit_message_text(text, chat_id=self.state["hhh_id"],
                                                                    message_id=chat.created_message_id,
                                                                    parse_mode=ParseMode.HTML)
        else:
            return await update.effective_message.reply_text(
                "invite link isn't in a correct form (tg://join?invite=[...] | https://t.me/joinchat/[...] | t.me/[...]")

    @Command()
    async def get_invite_link(self, update: Update, context: CallbackContext):
        if context.args:
            group_name: str = " ".join(context.args)
        else:
            return await update.effective_message.reply_text("Provide a group name moron")

        try:
            chat: Chat = [c for c in self.chats.values() if c.title == group_name][0]
        except IndexError:
            return await update.effective_message.reply_text("I don't know that group")

        if chat.invite_link:
            return await update.effective_message.reply_text(chat.invite_link)
        else:
            return await update.effective_message.reply_text("No invite link found for the given group")

    @Command(chat_admin=True)
    async def remove_invite_link(self, update: Update, context: CallbackContext):
        chat: Chat = context.chat_data["chat"]
        chat.invite_link = None
        return await self.update_hhh_message(context.chat_data["chat"])

    @Command()
    async def migrate_chat_id(self, update: Update, context: CallbackContext):
        self.logger.debug(f"Migrating {update.effective_message}")
        if not update.effective_message.migrate_from_chat_id:
            self.logger.warning("Aborting migration since `migrate_from_chat_id` is unset, see #49")
            return None

        from_id = int(update.effective_message.migrate_from_chat_id)
        to_id = int(update.effective_message.chat.id)

        self.logger.debug(f"Update chat_id to {to_id} (was: {from_id})")
        new_chat = context.chat_data["chat"]
        new_chat.id = to_id

        context.chat_data["chat"] = new_chat
        self.chats[to_id] = new_chat
        self.chats.pop(from_id)

    @Command()
    async def renew_diff_message(self, update: Update, context: CallbackContext):
        self.group_message_ids = []
        # retry doesn't update the recent changes
        return await self.update_hhh_message(context.chat_data["chat"])

    async def me(self):
        return await self.application.bot.get_me()

    @Command()
    async def noop(self, update: Update, context: CallbackContext):
        self.logger.debug(update)
        pass

    @Command()
    async def set_chat_photo(self, update: Update, context: CallbackContext):
        chat = context.chat_data["chat"]

        overwrite = "overwrite" in context.args
        if not overwrite:
            if (await self.application.bot.get_chat(chat.id)).photo:
                msg = "will not update photo since there already is one present, use `set_photo overwrite` instead"
                return await self.send_message(chat_id=chat.id, text=msg)

        thumbnail = generate_thumbnail(chat.title)
        if not thumbnail:
            return await self.send_message(chat_id=chat.id, text="failed to generate photo")
        try:
            return await self.application.bot.set_chat_photo(chat.id, thumbnail)
        except BadRequest as e:
            return await self.send_message(chat_id=chat.id, text=f"failed to update photo: {e}")

    @Command()
    async def set_premium_users_only(self, update: Update, context: CallbackContext):
        chat = context.chat_data["chat"]
        state = True

        if context.args:
            state = context.args[0].lower() == "true"

        chat.premium_users_only = state

        msg = "non premium-users will be kicked from this group when they interact with this chat again"
        return await self.send_message(chat_id=chat.id,
                                       text=msg)


def _split_messages(lines):
    message_length = 4096
    messages = []
    current_length = 0
    current_message = 0
    for line in lines:
        if len(messages) <= current_message:
            messages.append([])

        line_length = len(line)
        if current_length + line_length < message_length:
            current_length += line_length
            messages[current_message].append(line)
        else:
            current_length = 0
            current_message += 1

    return messages


def _validate_invite_link(link: str) -> bool:
    import re

    if re.match(r"https://t.me/(joinchat/)?.*", link):
        return True

    m = re.match(r"tg://join\?invite=.*", link)
    b = bool(m)
    return b
