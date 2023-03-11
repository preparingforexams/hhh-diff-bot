import inspect

import openai as openai
import requests
from openai import InvalidRequestError, OpenAIError
from requests import RequestException

from .logger import create_logger


def generate_thumbnail(title: str):
    logger = create_logger(inspect.currentframe().f_code.co_name)
    logger.debug(f"generate thumbnail for {title}")

    try:
        response = openai.Image.create(
            prompt=title,
            n=1,
            size="512x512",
            response_format="url",
        )
    except InvalidRequestError as e:
        # Only ever saw this because of their profanity filter. Of course the error
        # code was fucking None, so I would have to check the message to make sure
        # that the error is actually about their "safety system", but I won't.
        logger.debug("Got InvalidRequestError from OpenAI", exc_info=e)
        return None
    except OpenAIError as e:
        logger.error("An error occurred during image generation", exc_info=e)

        return None
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