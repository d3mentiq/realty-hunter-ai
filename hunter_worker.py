"""Background worker entrypoint running periodic hunter cycles."""

from __future__ import annotations

import logging
import sys
import time

from config import get_config
from hunter import run_hunter_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("worker")


def main() -> None:
    cfg = get_config()
    logger.info("Realty Hunter background worker started (interval: %d s)", cfg.scan_interval_sec)
    while True:
        try:
            logger.info("Starting scheduled scrape cycle...")
            run_hunter_cycle()
        except Exception as e:
            logger.error("Error in scheduled cycle: %s", e)

        logger.info("Sleeping for %d seconds...", cfg.scan_interval_sec)
        time.sleep(cfg.scan_interval_sec)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
        sys.exit(0)
