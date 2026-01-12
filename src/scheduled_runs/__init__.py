"""Scheduled runs package."""
import os
import time

from scheduled_runs.runlogging import setup_logging

MY_ENV = "tst"  # choose from prd, acc, dev, tst

os.environ["ENVIRONMENT"] = os.environ.get("ENVIRONMENT", MY_ENV)

os.environ["TZ"] = "Europe/Amsterdam"
time.tzset()

logger = setup_logging("ally")
logger.info(f'Your environment is {os.environ.get("ENVIRONMENT", "local")}')
