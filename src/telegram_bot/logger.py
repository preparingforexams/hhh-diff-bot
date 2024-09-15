import logging


def create_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    import sys

    logger = logging.Logger(name)
    ch = logging.StreamHandler(sys.stdout)

    formatting = f"[{name}] %(asctime)s\t%(levelname)s\t%(module)s.%(funcName)s#%(lineno)d | %(message)s"
    formatter = logging.Formatter(formatting)
    ch.setFormatter(formatter)

    logger.addHandler(ch)
    logger.setLevel(level)

    return logger
