import inspect
import json
import os
import random
from datetime import datetime
from typing import Dict, Optional

import telegram.bot

from main import get_token, update_state
from telegram_bot import create_logger
from telegram_bot.chat import ChatType


def choose_random_group(state: Dict, age_threshold_days: int) -> Optional[Dict]:
    choices = []
    for chat in state["chats"]:
        if chat["type"] == ChatType.PRIVATE:
            continue

        if "last_chat_event_isotime" in chat:
            last_chat_event_isotime = datetime.fromisoformat(chat["last_chat_event_isotime"])
            days_difference = (datetime.now() - last_chat_event_isotime).days
            if days_difference > age_threshold_days:
                choices.append(chat)
        else:
            # since there will be no available timestamp for old groups, add them by default
            choices.append(chat)

    if not choices:
        return None

    return random.choice(choices)


def random_reminder_phrase():
    return random.choice([
        "Knock Knock",
        "Ich vermisse Leute :(",
        "Visit my page for exclusive XxX content: definitelynotporn.com",
    ])


def send_reminder(group: Dict) -> Optional[telegram.Message]:
    logger = create_logger(inspect.currentframe().f_code.co_name)

    phrase = random_reminder_phrase()
    chat_id = group["id"]

    token = get_token()
    try:
        return telegram.bot.Bot(token).send_message(chat_id, phrase)
    except telegram.error.BadRequest:
        logger.exception(f"couldn't sent message to {chat_id} ({group['title']})", exc_info=True)


def remind(statefile: str) -> Optional[telegram.Message]:
    logger = create_logger(inspect.currentframe().f_code.co_name)

    age_threshold_days = int(os.getenv("AGE_THRESHOLD_DAYS") or "30")
    with open(statefile) as f:
        content = json.load(f)
    group = choose_random_group(content, age_threshold_days)
    if not group:
        logger.error(f"no group which didn't have any message in the last {age_threshold_days} days")
        return

    return send_reminder(group)


def update_last_event_timestamp(chat: Dict, chat_id: int) -> Dict:
    if chat["id"] == chat_id:
        chat["last_chat_event_isotime"] = datetime.now().isoformat()

    return chat


state_filepath = "state.json" if os.path.exists("state.json") else "/data/state.json"
result = remind(state_filepath)
if not result:
    create_logger("reminder").error("failed to send reminder message")
else:
    update_state(state_filepath,
                 chat_mutation_function=lambda c: update_last_event_timestamp(c, chat_id=result.chat_id))
