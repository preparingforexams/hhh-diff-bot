import os
import sys
import threading

from telegram.ext import CommandHandler, Updater, MessageHandler, Filters

from telegram_bot import Bot, create_logger


def cleanup_state(statefile):
    import json

    # noinspection PyShadowingNames
    with open(statefile) as f:
        # noinspection PyShadowingNames
        content = json.load(f)

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

    # noinspection PyShadowingNames
    with open(statefile, "w") as f:
        json.dump(dedup, f)


def start(bot_token: str, state_file: str):
    logger = create_logger("start")
    logger.debug("Start bot")

    updater = Updater(token=bot_token, use_context=True)
    bot = Bot(updater, state_file)

    dispatcher = updater.dispatcher

    logger.debug("Register command handlers")
    # CommandHandler
    dispatcher.add_handler(CommandHandler("users", bot.show_users))
    dispatcher.add_handler(CommandHandler("get_invite_link", bot.get_invite_link, pass_args=True))

    # main_admin
    dispatcher.add_handler(CommandHandler("delete_chat_by_id", bot.delete_chat_by_id))

    # chat_admin
    dispatcher.add_handler(CommandHandler("delete_chat", bot.delete_chat))
    dispatcher.add_handler(CommandHandler("get_data", bot.get_data))
    dispatcher.add_handler(CommandHandler("mute", bot.mute, pass_args=True))
    dispatcher.add_handler(CommandHandler("unmute", bot.unmute, pass_args=True))
    dispatcher.add_handler(CommandHandler("kick", bot.kick, pass_args=True))
    dispatcher.add_handler(CommandHandler("add_invite_link", bot.add_invite_link, pass_args=True))
    dispatcher.add_handler(CommandHandler("remove_invite_link", bot.remove_invite_link))
    dispatcher.add_handler(CommandHandler("renew_diff_message", bot.renew_diff_message))

    # Debugging
    dispatcher.add_handler(CommandHandler("status", bot.status))
    dispatcher.add_handler(CommandHandler("server_time", bot.server_time))
    dispatcher.add_handler(CommandHandler("version", bot.version))

    # MessageHandler
    dispatcher.add_handler(
        MessageHandler(Filters.text, bot.handle_message))
    dispatcher.add_handler(
        MessageHandler(Filters.status_update.left_chat_member, bot.handle_left_chat_member))
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, bot.new_member))
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_title, bot.new_chat_title))
    dispatcher.add_handler(MessageHandler(Filters.status_update.chat_created, bot.chat_created))
    dispatcher.add_handler(MessageHandler(Filters.status_update.migrate, bot.migrate_chat_id))
    dispatcher.add_handler(MessageHandler(Filters.all, bot.noop))

    logger.debug(f"Read state from {state_file}")
    if os.path.exists(state_file):
        with open(state_file) as file:
            try:
                state = json.load(file)
                bot.set_state(state)
            except json.decoder.JSONDecodeError as e:
                logger.warning(f"Unable to load previous state: {e}")

    try:
        if sys.argv[1] == "--testrun":
            logger.info("Scheduling exit in 5 seconds")

            def _exit():
                logger.info("Exiting")
                updater.stop()
                updater.is_idle = False

            timer = threading.Timer(5, _exit)
            timer.setDaemon(True)
            timer.start()
    except IndexError:
        pass

    logger.info("Running")
    updater.start_polling()
    updater.idle()


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
    state_filepath = "state.json" if os.path.exists("state.json") else "/data/state.json"
    cleanup_state(state_filepath)
    import json

    token = get_token()

    # noinspection PyBroadException
    try:
        start(token, state_filepath)
    except Exception as e:
        create_logger("__main__").error(e, exc_info=True)
        sys.exit(1)
