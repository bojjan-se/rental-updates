"""Centralized logging configuration for the rental scraper."""

import logging
import logging.handlers
import os
import sys


def setup_logging(log_dir: str = "logs", log_file: str = "scheduler.log") -> None:
    """
    Configure logging with console and rotating file handlers.

    Args:
        log_dir: Directory for log files
        log_file: Name of the log file
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Rotating file handler (10MB max, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    file_handler.setFormatter(formatter)

    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler]
    )
