import json
import os
import random
from datetime import datetime
from typing import Dict, Optional

from telegram_bot.chat import ChatType


def choose_random_group(state: Dict, age_threshold_days: int) -> Optional[Dict]:
    choices = []
    for chat in state["chats"]:
        if chat["type"] == ChatType.PRIVATE:
            continue

        if "last_message_timestamp" in chat:
            last_message_timestamp = datetime.fromisoformat(chat["last_message_timestamp"])
            days_difference = (datetime.now() - last_message_timestamp).days
            if days_difference > age_threshold_days:
                choices.append(chat)

    if not choices:
        return None

    return random.choice(choices)


def remind(statefile: str) -> Optional[Dict]:
    age_threshold_days = int(os.getenv("AGE_THRESHOLD_DAYS") or "14")
    with open(statefile) as f:
        content = json.load(f)
        return choose_random_group(content, age_threshold_days)
