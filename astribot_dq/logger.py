import logging
import os
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler

from astribot_dq.constant import ENV_LOG_SIZE


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds ANSI colour codes by log level."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def _generate_log_file_path():
    exec_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    log_dir = os.path.join(exec_path, "log")
    os.makedirs(log_dir, exist_ok=True)
    dir_name = os.path.dirname(os.path.abspath(sys.argv[0])).split("/")[-1]
    log_file_name = (
        time.strftime(
            f"{dir_name}_%Y-%m-%d_%H-%M-%S-{uuid.uuid4()}",
            time.localtime(time.time()),
        )
        + ".log"
    )
    return os.path.join(log_dir, log_file_name)


def create_logger(log_size_mb: int):
    if hasattr(create_logger, "_logger"):
        return create_logger._logger

    logger = logging.getLogger(str(uuid.uuid4()))
    logger.setLevel(logging.DEBUG)

    log_file_path = _generate_log_file_path()
    file_handler = RotatingFileHandler(
        log_file_path, maxBytes=log_size_mb * 1024 * 1024, backupCount=20
    )
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    plain_formatter = logging.Formatter(
        "[%(asctime)s][%(filename)s:%(lineno)d][%(levelname)s] %(message)s"
    )
    colored_formatter = ColoredFormatter(
        "[%(asctime)s][%(filename)s:%(lineno)d][%(levelname)s] %(message)s"
    )

    file_handler.setFormatter(plain_formatter)
    console_handler.setFormatter(colored_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    create_logger._logger = logger
    logger.info(f"Log file: {log_file_path}, max size: {log_size_mb} MB")
    return logger


str_log_size_mb = int(os.environ.get(ENV_LOG_SIZE, "10"))
g_logger = create_logger(str_log_size_mb)
