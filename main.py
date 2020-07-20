import os
import sys
import threading

import sentry_sdk
from telegram import TelegramError
from telegram.ext import CommandHandler, Updater, MessageHandler, Filters

from telegram_bot import Bot, create_logger


def handle_telegram_error(error: TelegramError):
    create_logger("handle_telegram_error").error(error)


def start(bot_token: str):
    logger = create_logger("start")
    logger.debug("Start bot")

    updater = Updater(token=bot_token, use_context=True)
    bot = Bot(updater)

    dispatcher = updater.dispatcher

    logger.debug("Register command handlers")
    # CommandHandler
    dispatcher.add_handler(CommandHandler("users", bot.show_users))

    # chat_admin
    dispatcher.add_handler(CommandHandler("delete_chat", bot.delete_chat))
    dispatcher.add_handler(CommandHandler("get_data", bot.get_data))
    dispatcher.add_handler(CommandHandler("mute", bot.mute, pass_args=True))
    dispatcher.add_handler(CommandHandler("unmute", bot.unmute, pass_args=True))
    dispatcher.add_handler(CommandHandler("kick", bot.kick, pass_args=True))

    # Debugging
    dispatcher.add_handler(CommandHandler("status", bot.status))
    dispatcher.add_handler(CommandHandler("server_time", bot.server_time))
    dispatcher.add_handler(CommandHandler("version", bot.version))

    # MessageHandler
    dispatcher.add_handler(MessageHandler(Filters.command, bot.handle_unknown_command))
    dispatcher.add_handler(
        MessageHandler(Filters.text, bot.handle_message))
    dispatcher.add_handler(
        MessageHandler(Filters.status_update.left_chat_member, bot.handle_left_chat_member))
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, bot.new_member))

    # ErrorHandler
    dispatcher.add_error_handler(
        lambda _bot, _update, error: handle_telegram_error(error)
    )

    state_file = "state.json"
    logger.debug(f"Read state from {state_file}")
    if os.path.exists(state_file):
        with open(state_file) as file:
            try:
                state = json.load(file)
            except json.decoder.JSONDecodeError as e:
                logger.warning(f"Unable to load previous state: {e}")
                state = {}

        bot.set_state(state)

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


if __name__ == "__main__":
    import json

    raw_token = os.getenv("BOT_TOKEN") 
    token = raw_token.strip() if raw_token else None
    sentry_dsn = None
    if not token and os.path.exists("secrets.json"):
        with open("secrets.json") as f:
            content = json.load(f)
            token = content.get('token', os.getenv("BOT_TOKEN"))
            if not token:
                raise ValueError("`token` not defined, either set `BOT_TOKEN` or `token` in `secrets.json`")

            sentry_dsn = content.get('sentry_dsn')

    if not token:
        raise ValueError("No token has been specified")

    sentry_sdk.init(sentry_dsn)

    # noinspection PyBroadException
    try:
        start(token)
    except Exception as e:
        sentry_sdk.capture_exception()
        create_logger("__main__").error(e)
        sys.exit(1)
