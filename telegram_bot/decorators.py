from __future__ import annotations

import inspect
from datetime import timedelta

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import CallbackContext

from . import bot
from . import chat
from . import logger
from . import user


class Command:
    def __init__(self, chat_admin: bool = False, main_admin: bool = False):
        self.chat_admin = chat_admin
        self.main_admin = main_admin

    @staticmethod
    def _add_chat(clazz, update: Update, context: CallbackContext) -> chat.Chat:
        log = logger.create_logger(f"_add_chat")
        log.debug(f"Start with {update.effective_chat.id}")
        new_chat = clazz.chats.get(update.effective_chat.id)
        if new_chat is None:
            log.debug("Creating new chat")
            new_chat = chat.Chat(update.effective_chat.id, clazz.updater.bot)
            new_chat.title = update.effective_chat.title
            clazz.chats[new_chat.id] = new_chat

            log.debug(f"Created new chat ({new_chat})")

        context.chat_data["chat"] = new_chat

        log.debug(f"End with {new_chat}")
        return new_chat

    @staticmethod
    def _add_user(update: Update, context: CallbackContext) -> user.User:
        return user.User.from_tuser(update.effective_user)

    def __call__(self, func):
        def wrapped_f(*args, **kwargs):
            exception = None
            log = logger.create_logger(f"command_{func.__name__}")
            log.debug("Start")
            log.debug(f"args: {args} | kwargs: {kwargs}")

            signature = inspect.signature(func)
            arguments = signature.bind(*args, **kwargs).arguments

            clazz: bot.Bot = arguments.get("self")
            update: Update = arguments.get("update")
            context: CallbackContext = arguments.get("context")
            execution_message: str = f"Executing {func.__name__}"
            finished_execution_message: str = f"Finished executing {func.__name__}"

            if not update:
                log.debug("Execute function due to coming directly from the bot.")

                log.debug(execution_message)
                result = func(*args, **kwargs)
                log.debug(finished_execution_message)

                return result

            log.debug(f"message from user: {update.effective_user.first_name}")
            current_chat = context.chat_data.get("chat")
            if not current_chat:
                current_chat = self._add_chat(clazz, update, context)
            if not current_chat.title:
                log.debug(f"Assign title ({update.effective_chat.title}) to chat ({current_chat}) (previously missing)")
                current_chat.title = update.effective_chat.title

            if not current_chat.invite_link \
                    and current_chat.type != chat.ChatType.PRIVATE and current_chat.type != chat.ChatType.UNDEFINED \
                    and clazz.me().id in [admin.user.id for admin in
                                          current_chat.bot.get_chat_administrators(chat_id=current_chat.id)]:
                log.info(f"creating invite link for {current_chat.title}")
                try:
                    current_chat.invite_link = update.effective_chat.create_invite_link().invite_link
                    clazz.update_hhh_message(current_chat, retry=False)
                except BadRequest:
                    log.exception("failed creating invite link or updating message: ", exc_info=True)
                    pass

            current_chat.type = update.effective_chat.type
            current_chat.description = update.effective_chat.description

            if not clazz.chats.get(current_chat.id):
                clazz.chats[current_chat.id] = current_chat

            current_user = current_chat.get_user_by_id(update.effective_user.id)
            if not current_user:
                current_user = self._add_user(update, context)

            current_chat.add_user(current_user)
            context.user_data["user"] = current_user

            if self.main_admin:
                if current_chat.id in clazz.main_admin_ids:
                    log.debug("Execute function due to coming from the main_chat")
                else:
                    message = f"Chat {chat} is not allowed to perform this action."
                    log.warning(message)
                    clazz.mute_user(chat_id=current_chat.id, user=current_user, until_date=timedelta(minutes=15),
                                    reason=message)
                    exception = PermissionError()

            if self.chat_admin:
                if current_chat.type == chat.ChatType.PRIVATE:
                    log.debug("Execute function due to coming from a private chat")
                elif current_user in current_chat.administrators():
                    log.debug(
                        f"User ({current_user.name}) is a chat admin and therefore allowed to perform this action, executing")
                elif update.effective_user.name == "@GroupAnonymousBot" and update.effective_user.is_bot and update.effective_user.link == "https://t.me/GroupAnonymousBot" and update.effective_user.first_name == "Group" and update.effective_user.full_name == "Group":
                    log.debug("anonymous mode for admins is allowed")
                else:
                    log.error(
                        f"User ({current_user.name}) isn't a chat_admin and is not allowed to perform this action.")
                    exception = PermissionError()

            if update.effective_message:
                log.debug(f"Message: {update.effective_message.text}")
                current_chat.add_message(update)  # Needs user in chat

            log.debug(execution_message)
            try:
                if exception:
                    raise exception

                result = func(*args, **kwargs)
                log.debug(finished_execution_message)
                return result
            except PermissionError:
                if update.effective_message:
                    update.effective_message.reply_text(
                        f"You ({current_user.name}) are not allowed to perform this action.")
            except Exception as e:
                # Log for debugging purposes
                log.error(str(e), exc_info=True)

                raise e
            finally:
                clazz.save_state()
                log.debug("End")

        return wrapped_f


def group(function):
    def wrapper(clz: chat.Chat, *args, **kwargs):
        log = logger.create_logger(f"group_wrapper_{function.__name__}")
        log.debug("Start")
        if not (hasattr(clz, "type") and (isinstance(clz.type, str) or isinstance(clz.type, chat.ChatType))):
            message = "group decorator can only be used on a class which has a `type` attribute of type `str` or `chat.ChatType`."
            log.error(message)
            raise TypeError(message)

        if clz.type == chat.ChatType.PRIVATE:
            log.debug("Not executing group function in private chat.")
            return False

        log.debug("Execute function")
        return function(clz, *args, **kwargs)

    return wrapper
