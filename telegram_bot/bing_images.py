import inspect
import os
from typing import Optional

import requests

from .logger import create_logger


def search_bing_image(term: str) -> Optional[str]:
    logger = create_logger(inspect.currentframe().f_code.co_name)
    subscription_key = os.getenv("BING_IMAGE_API_SEARCH_KEY")
    search_url = "https://api.bing.microsoft.com/v7.0/images/search"

    headers = {"Ocp-Apim-Subscription-Key": subscription_key}
    params = {
        "q": term,
        "license": "public",
        "imageType": "photo",
        "safeSearch": "off",
        "setLang": "de",
        "count": 1,
    }

    response = requests.get(search_url, headers=headers, params=params)
    logger.debug("got response")
    response.raise_for_status()
    results = response.json()
    logger.debug("got result")

    try:
        return results["value"][0]["thumbnailUrl"]
    except IndexError:
        logger.error(f"no images found for `{term}`")
        return None

