"""Normalize BKK API predictions into database-ready entities."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional


def count_delay_seconds(
    scheduled_departure: datetime,
    predicted_departure: datetime,
) -> int:
    """Count delay with the Phase 4 formula: predicted - scheduled."""

    return int((predicted_departure - scheduled_departure).total_seconds())


def categorize_delay(delay_seconds: int) -> str:
    if delay_seconds < -60:
        return "early"
    if delay_seconds <= 60:
        return "on_time"
    if delay_seconds <= 180:
        return "minor_delay"
    if delay_seconds <= 360:
        return "medium_delay"
    return "major_delay"


def create_observation_id(
    collection_run_id: str,
    trip_id: str,
    stop_id: str,
    scheduled_departure: datetime,
    index: int,
    collected_at: Optional[datetime] = None,
) -> str:
    if collected_at is not None:
        collected_minute = _round_down_to_minute(collected_at)
        natural_key = "|".join(
            (
                trip_id,
                stop_id,
                scheduled_departure.isoformat(),
                collected_minute.isoformat(),
            )
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, natural_key))

    natural_key = "|".join(
        (
            collection_run_id,
            trip_id,
            stop_id,
            scheduled_departure.isoformat(),
            str(index),
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, natural_key))


def create_observation_duplicate_key(
    trip_id: str,
    stop_id: str,
    scheduled_departure: datetime,
    collected_at: datetime,
) -> str:
    collected_minute = _round_down_to_minute(collected_at)
    return "|".join(
        (
            trip_id,
            stop_id,
            scheduled_departure.isoformat(),
            collected_minute.isoformat(),
        )
    )


def _round_down_to_minute(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(second=0, microsecond=0)
