from datetime import datetime, timezone

from bkk_delays.delay_processor import (
    categorize_delay,
    count_delay_seconds,
    create_observation_duplicate_key,
    create_observation_id,
)


def test_count_delay_seconds_uses_phase_4_formula():
    scheduled = datetime(2026, 5, 16, 14, 5, tzinfo=timezone.utc)
    predicted = datetime(2026, 5, 16, 14, 7, tzinfo=timezone.utc)

    assert count_delay_seconds(scheduled, predicted) == 120


def test_categorize_delay_matches_phase_4_boundaries():
    assert categorize_delay(-61) == "early"
    assert categorize_delay(-60) == "on_time"
    assert categorize_delay(60) == "on_time"
    assert categorize_delay(61) == "minor_delay"
    assert categorize_delay(180) == "minor_delay"
    assert categorize_delay(181) == "medium_delay"
    assert categorize_delay(360) == "medium_delay"
    assert categorize_delay(361) == "major_delay"


def test_create_observation_id_is_stable_for_same_natural_key():
    scheduled = datetime(2026, 5, 16, 14, 5, tzinfo=timezone.utc)

    first = create_observation_id(
        "RUN_1",
        "BKK_TRIP_1",
        "BKK_STOP_1",
        scheduled,
        0,
    )
    second = create_observation_id(
        "RUN_1",
        "BKK_TRIP_1",
        "BKK_STOP_1",
        scheduled,
        0,
    )

    assert first == second


def test_create_observation_id_ignores_collection_time_when_provided():
    scheduled = datetime(2026, 5, 16, 14, 5, tzinfo=timezone.utc)
    collected_first = datetime(2026, 5, 16, 14, 0, 1, tzinfo=timezone.utc)
    collected_second = datetime(2026, 5, 16, 14, 20, 59, tzinfo=timezone.utc)

    first = create_observation_id(
        "RUN_1",
        "BKK_TRIP_1",
        "BKK_STOP_1",
        scheduled,
        0,
        collected_at=collected_first,
    )
    second = create_observation_id(
        "RUN_2",
        "BKK_TRIP_1",
        "BKK_STOP_1",
        scheduled,
        1,
        collected_at=collected_second,
    )

    assert first == second


def test_create_observation_duplicate_key_ignores_collection_time():
    scheduled = datetime(2026, 5, 16, 14, 5, tzinfo=timezone.utc)

    duplicate_key = create_observation_duplicate_key(
        "BKK_TRIP_1",
        "BKK_STOP_1",
        scheduled,
    )

    assert duplicate_key == "BKK_TRIP_1|BKK_STOP_1|2026-05-16T14:05:00+00:00"
