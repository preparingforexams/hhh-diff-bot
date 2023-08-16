import json
import os
import sys
from typing import Callable, Dict

from kubernetes import config, client
# noinspection PyPackageRequirements
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from telegram_bot import Bot, create_logger
from telegram_bot.state import State, ConfigmapState


def update_state(state_filepath: str, *, state_mutation_function: Callable[[Dict], Dict] | None = None,
                 chat_mutation_function: Callable[[Dict], Dict] | None = None):
    import json
    if not state_mutation_function:
        state_mutation_function = lambda x: x
    if not chat_mutation_function:
        chat_mutation_function = lambda x: x

    with open(state_filepath) as f:
        state = json.load(f)
    new_chats = []
    state = state_mutation_function(state)
    for chat in state["chats"]:
        new_chats.append(chat_mutation_function(chat))

    state["chats"] = new_chats
    with open(state_filepath, "w+") as f:
        json.dump(state, f)


def cleanup_state(content: Dict) -> Dict:
    dedup = content.copy()
    dedup["chats"] = []

    for chat in content["chats"]:
        chat_id = chat.get("id")
        chat_title = chat.get("title")
        if chat_id is None or chat_id == "None":
            continue

        if isinstance(chat_id, str):
            if any(c.get("id") == int(chat_id) for c in content["chats"]):
                continue
            else:
                chat["id"] = int(chat_id)
        elif chat_title and any(c.get("title") == chat_title for c in dedup["chats"]):
            continue

        dedup["chats"].append(chat)

    return dedup


def get_state(initial_state: dict) -> State:
    try:
        config.load_incluster_config()
    except config.config_exception.ConfigException:
        config.load_kube_config()

    kubernetes_api_client = client.CoreV1Api()
    return ConfigmapState(kubernetes_api_client, initial_state)


def start(bot_token: str, state: State):
    logger = create_logger("start")
    logger.debug("Start bot")

    application = ApplicationBuilder().token(bot_token).build()
    bot = Bot(application, state)

    logger.debug("Register command handlers")
    # CommandHandler
    application.add_handler(CommandHandler("users", bot.show_users))
    application.add_handler(CommandHandler("get_invite_link", bot.get_invite_link))
    application.add_handler(CommandHandler("set_photo", bot.set_chat_photo))

    # main_admin
    application.add_handler(CommandHandler("delete_chat_by_id", bot.delete_chat_by_id))

    # chat_admin
    application.add_handler(CommandHandler("delete_chat", bot.delete_chat))
    application.add_handler(CommandHandler("get_data", bot.get_data))
    application.add_handler(CommandHandler("mute", bot.mute))
    application.add_handler(CommandHandler("unmute", bot.unmute))
    application.add_handler(CommandHandler("kick", bot.kick))
    application.add_handler(CommandHandler("add_invite_link", bot.add_invite_link))
    application.add_handler(CommandHandler("remove_invite_link", bot.remove_invite_link))
    application.add_handler(CommandHandler("renew_diff_message", bot.renew_diff_message))
    application.add_handler(CommandHandler("set_premium_users_only", bot.set_premium_users_only))

    # Debugging
    application.add_handler(CommandHandler("status", bot.status))
    application.add_handler(CommandHandler("server_time", bot.server_time))
    application.add_handler(CommandHandler("version", bot.version))

    application.add_handler(
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, bot.handle_left_chat_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bot.new_member))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_TITLE, bot.new_chat_title))
    application.add_handler(MessageHandler(filters.StatusUpdate.CHAT_CREATED, bot.chat_created))
    application.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, bot.migrate_chat_id))
    application.add_handler(MessageHandler(filters.ALL, bot.noop))

    logger.info("Running")
    application.run_polling()


def get_token() -> str:
    raw_token = os.getenv("BOT_TOKEN")
    # noinspection PyShadowingNames
    token = raw_token.strip() if raw_token else None
    if not token and os.path.exists("secrets.json"):
        with open("secrets.json") as f:
            content = json.load(f)
            # noinspection PyShadowingNames
            token = content.get('token', os.getenv("BOT_TOKEN"))
            if not token:
                raise ValueError("`token` not defined, either set `BOT_TOKEN` or `token` in `secrets.json`")

    return token


if __name__ == "__main__":
    token = get_token()

    state = get_state({
        "group_message_id": [],
        "recent_changes": [],
        "hhh_id": -1001473841450,
        "pinned_message_id": None
    })

    # noinspection PyBroadException
    try:
        start(token, state)
    except Exception as e:
        create_logger("__main__").error(e, exc_info=True)
        sys.exit(1)
