"""
Sistema de logging estructurado con rotación de archivos.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Consola
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # Archivo con rotación (10 MB x 5 backups)
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = settings.LOGS_DIR / f"{name.split('.')[-1]}.log"
    fh = RotatingFileHandler(log_file, maxBytes=10_485_760, backupCount=5, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
