"""Cloud Run Function entry point for scheduled BKK collection."""

from __future__ import annotations

import logging

import functions_framework

from bkk_delays.collect_bkk_data import run_collection


LOGGER = logging.getLogger(__name__)


@functions_framework.cloud_event
def collect_bkk_data(cloud_event: object) -> None:
    """Handle a Pub/Sub CloudEvent and run one monitored-stop collection."""

    summary = run_collection()
    LOGGER.info("Scheduled BKK collection finished: %s", summary.to_dict())

