from datetime import datetime, timedelta, timezone

from bkk_delays.bigquery_repository import (
    DELAY_OBSERVATIONS_TABLE,
    DELAY_PREDICTION_MODEL,
    BigQueryRepository,
    BigQueryStatistics,
    MORICZ_UJBUDA_HEADSIGN,
    empty_statistics,
    load_named_sql_queries,
    statistics_from_observations,
)
from bkk_delays.config import AppConfig
from bkk_delays.models import CollectionRun, DelayObservation, Route, SearchCollectionBatch, Stop


def _config(use_bigquery: bool) -> AppConfig:
    return AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="test-project",
        firestore_database_id="",
        bigquery_dataset="bkk_analytics",
        bigquery_table=DELAY_OBSERVATIONS_TABLE,
        use_firestore=False,
        use_bigquery=use_bigquery,
    )


def _batch() -> SearchCollectionBatch:
    now = datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc)
    return SearchCollectionBatch(
        routes=(Route(id="BKK_3040", short_name="4", route_type="TRAM"),),
        stops=(Stop(id="BKK_STOP_1", name="Oktogon M", lat=47.505, lon=19.063),),
        collection_run=CollectionRun(
            id="RUN_1",
            started_at=now,
            finished_at=now,
            status="success",
            records_saved=1,
        ),
        delay_observations=(
            DelayObservation(
                id="OBS_1",
                collection_run_id="RUN_1",
                route_id="BKK_3040",
                stop_id="BKK_STOP_1",
                trip_id="BKK_TRIP_1",
                headsign="Ujbuda-kozpont M",
                direction_id="1",
                stop_sequence=12,
                scheduled_departure=now,
                predicted_departure=now,
                delay_seconds=0,
                delay_category="on_time",
                created_at=now,
            ),
        ),
    )


def test_disabled_bigquery_repository_returns_empty_statistics():
    repository = BigQueryRepository(_config(use_bigquery=False))

    stats = repository.load_statistics()

    assert stats == empty_statistics()


def test_bigquery_repository_does_not_expose_write_api():
    client = FakeBigQueryClient()
    repository = BigQueryRepository(_config(use_bigquery=True), client=client)

    assert not hasattr(repository, "save_search_collection_batch")
    assert not hasattr(repository, "ensure_dataset_and_tables")


def test_average_delay_by_stop_uses_readable_unlimited_sql():
    client = FakeBigQueryClient(
        query_results=[
            [
                {
                    "stop_id": "BKK_STOP_1",
                    "stop_name": "Oktogon M",
                    "headsign": "Ujbuda-kozpont M",
                    "observation_count": 3,
                    "average_delay_seconds": 90.5,
                }
            ]
        ]
    )
    repository = BigQueryRepository(_config(use_bigquery=True), client=client)

    rows = repository.average_delay_by_stop()

    assert rows[0].stop_name == "Oktogon M"
    assert rows[0].headsign == "Ujbuda-kozpont M"
    assert rows[0].average_delay_seconds == 90.5
    assert "LIMIT" not in client.queries[0]
    assert "`test-project.bkk_analytics.delay_observations`" in client.queries[0]
    assert "observation.route_id IN ('BKK_3040', 'BKK_3060')" in client.queries[0]
    assert "REGEXP_REPLACE" not in client.queries[0]


def test_predicted_delay_by_station_uses_bigquery_ml_model_at_current_time():
    client = FakeBigQueryClient(
        query_results=[
            [
                {
                    "stop_id": "BKK_STOP_1",
                    "stop_name": "Oktogon M",
                    "headsign": "Ujbuda-kozpont M",
                    "prediction_time": "2026-05-16T14:25:00",
                    "predicted_delay_seconds": 75.5,
                }
            ]
        ]
    )
    repository = BigQueryRepository(_config(use_bigquery=True), client=client)

    rows = repository.predicted_delay_by_station()

    assert rows[0].stop_name == "Oktogon M"
    assert rows[0].headsign == "Ujbuda-kozpont M"
    assert rows[0].predicted_delay_seconds == 75.5
    assert "ML.PREDICT" in client.queries[0]
    assert f"`test-project.bkk_analytics.{DELAY_PREDICTION_MODEL}`" in client.queries[0]
    assert "observation.route_id IN ('BKK_3040', 'BKK_3060')" in client.queries[0]
    assert "route_id,\n        headsign" not in client.queries[0]
    assert "moricz zsigmond korter m" in client.queries[0]
    assert " / " in client.queries[0]
    assert "CURRENT_DATETIME('Europe/Budapest')" in client.queries[0]
    assert "prediction_context" in client.queries[0]
    assert "current_time.prediction_time" not in client.queries[0]
    assert "LIMIT" not in client.queries[0]


def test_delayed_ratio_by_time_period_includes_average_delay_by_departure_hour():
    client = FakeBigQueryClient(
        query_results=[
            [
                {
                    "period_start": "2026-05-16T14:00:00",
                    "observation_count": 5,
                    "delayed_count": 4,
                    "delayed_ratio": 0.8,
                    "average_delay_seconds": 96.5,
                }
            ]
        ]
    )
    repository = BigQueryRepository(_config(use_bigquery=True), client=client)

    rows = repository.delayed_ratio_by_time_period()

    assert rows[0].average_delay_seconds == 96.5
    assert "DATETIME_TRUNC(scheduled_departure, HOUR)" in client.queries[0]
    assert "AVG(delay_seconds) AS average_delay_seconds" in client.queries[0]
    assert "@hours" not in client.queries[0]
    assert "DATETIME_SUB" not in client.queries[0]
    assert "created_at" not in client.queries[0]


def test_bigquery_sql_queries_are_loaded_from_sql_file():
    queries = load_named_sql_queries()

    assert "predicted_delay_by_station" in queries
    assert "average_delay_by_stop" in queries
    assert "delay_by_direction" not in queries
    assert "delay_progression_by_stop_sequence" not in queries
    assert "most_problematic_stops" in queries
    assert "{delay_observations_table}" in queries["average_delay_by_stop"]
    assert "headsign" in queries["average_delay_by_stop"]
    assert "móricz zsigmond körtér m" in queries["average_delay_by_stop"]
    assert MORICZ_UJBUDA_HEADSIGN in queries["average_delay_by_stop"]
    assert "observation.route_id IN ('BKK_3040', 'BKK_3060')" in queries[
        "average_delay_by_stop"
    ]
    assert "REGEXP_REPLACE" not in queries["average_delay_by_stop"]
    assert "LIMIT" not in queries["average_delay_by_stop"]
    assert "DATETIME_TRUNC(scheduled_departure, HOUR)" in queries[
        "delayed_ratio_by_time_period"
    ]
    assert "AVG(delay_seconds) AS average_delay_seconds" in queries[
        "delayed_ratio_by_time_period"
    ]
    assert "@hours" not in queries["delayed_ratio_by_time_period"]
    assert "DATETIME_SUB" not in queries["delayed_ratio_by_time_period"]
    assert "created_at" not in queries["delayed_ratio_by_time_period"]
    assert "{delay_prediction_model}" in queries["predicted_delay_by_station"]
    assert "ML.PREDICT" in queries["predicted_delay_by_station"]
    assert "observation.route_id IN ('BKK_3040', 'BKK_3060')" in queries[
        "predicted_delay_by_station"
    ]
    assert "route_id,\n        headsign" not in queries["predicted_delay_by_station"]
    assert "móricz zsigmond körtér m" in queries[
        "predicted_delay_by_station"
    ]
    assert " / " in queries["predicted_delay_by_station"]
    assert "CURRENT_DATETIME('Europe/Budapest')" in queries[
        "predicted_delay_by_station"
    ]
    assert "prediction_context" in queries["predicted_delay_by_station"]
    assert "current_time.prediction_time" not in queries[
        "predicted_delay_by_station"
    ]


def test_statistics_from_observations_builds_sample_analytics():
    stats = statistics_from_observations(
        _batch().delay_observations,
        _batch().stops,
    )

    assert isinstance(stats, BigQueryStatistics)
    assert stats.average_delay_by_stop[0].stop_name == "Oktogon M"
    assert stats.average_delay_by_stop[0].headsign == MORICZ_UJBUDA_HEADSIGN


def test_statistics_from_observations_separates_same_stop_by_headsign():
    batch = _batch()
    observation = batch.delay_observations[0]
    opposite_direction = DelayObservation(
        id="OBS_2",
        collection_run_id=observation.collection_run_id,
        route_id="BKK_3060",
        stop_id=observation.stop_id,
        trip_id="BKK_TRIP_2",
        headsign="Szell Kalman ter M",
        direction_id="0",
        stop_sequence=13,
        scheduled_departure=observation.scheduled_departure,
        predicted_departure=observation.predicted_departure,
        delay_seconds=180,
        delay_category="minor_delay",
        created_at=observation.created_at,
    )

    stats = statistics_from_observations(
        (*batch.delay_observations, opposite_direction),
        batch.stops,
    )

    assert [row.headsign for row in stats.average_delay_by_stop] == [
        "Szell Kalman ter M",
        MORICZ_UJBUDA_HEADSIGN,
    ]
    assert [row.stop_name for row in stats.average_delay_by_stop] == [
        "Oktogon M",
        "Oktogon M",
    ]


def test_statistics_from_observations_groups_ujbuda_and_moricz_headsigns():
    batch = _batch()
    observation = batch.delay_observations[0]
    moricz_observation = DelayObservation(
        id="OBS_2",
        collection_run_id=observation.collection_run_id,
        route_id=observation.route_id,
        stop_id=observation.stop_id,
        trip_id="BKK_TRIP_2",
        headsign="Móricz Zsigmond körtér M",
        direction_id=observation.direction_id,
        stop_sequence=observation.stop_sequence,
        scheduled_departure=observation.scheduled_departure,
        predicted_departure=observation.predicted_departure,
        delay_seconds=180,
        delay_category="minor_delay",
        created_at=observation.created_at,
    )

    stats = statistics_from_observations(
        (*batch.delay_observations, moricz_observation),
        batch.stops,
    )

    assert len(stats.average_delay_by_stop) == 1
    assert stats.average_delay_by_stop[0].headsign == MORICZ_UJBUDA_HEADSIGN
    assert stats.average_delay_by_stop[0].observation_count == 2


def test_statistics_from_observations_groups_period_by_scheduled_departure():
    batch = _batch()
    observation = batch.delay_observations[0]
    later_scheduled_departure = DelayObservation(
        id="OBS_2",
        collection_run_id=observation.collection_run_id,
        route_id=observation.route_id,
        stop_id=observation.stop_id,
        trip_id="BKK_TRIP_2",
        headsign=observation.headsign,
        direction_id=observation.direction_id,
        stop_sequence=observation.stop_sequence,
        scheduled_departure=observation.scheduled_departure + timedelta(hours=2),
        predicted_departure=observation.predicted_departure + timedelta(hours=2),
        delay_seconds=180,
        delay_category="minor_delay",
        created_at=observation.created_at,
    )

    stats = statistics_from_observations(
        (*batch.delay_observations, later_scheduled_departure),
        batch.stops,
    )

    assert [row.period_start.hour for row in stats.delayed_ratio_by_period] == [
        observation.scheduled_departure.hour,
        later_scheduled_departure.scheduled_departure.hour,
    ]
    assert [row.average_delay_seconds for row in stats.delayed_ratio_by_period] == [
        observation.delay_seconds,
        later_scheduled_departure.delay_seconds,
    ]


class FakeBigQueryClient:
    project = "test-project"

    def __init__(self, query_results=None):
        self.queries = []
        self.query_results = list(query_results or [])

    def query(self, sql, job_config=None):
        self.queries.append(sql)
        rows = self.query_results.pop(0) if self.query_results else []
        return FakeQueryJob(rows)


class FakeQueryJob:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return self.rows
