import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

def setup_logging(directory: Path) -> logging.Logger:
    logger = logging.getLogger("investment_app")
    if not logger.handlers:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "application.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
