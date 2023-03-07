import inspect

import openai as openai
import requests
from requests import RequestException

from .logger import create_logger


def generate_thumbnail(title: str):
    logger = create_logger(inspect.currentframe().f_code.co_name)
    logger.debug(f"generate thumbnail for {title}")

    response = openai.Image.create(
        prompt=title,
        n=1,
        size="512x512",
        response_format="url",
    )
    url = response["data"][0]["url"]

    try:
        response = requests.get(url, timeout=60)
    except RequestException as e:
        logger.error("Could not get generated image", exc_info=e)
        return None

    if response.status_code >= 400:
        logger.error(
            "Got unsuccessful response %d when trying to get image",
            response.status_code,
        )
        return None

    return response.content
