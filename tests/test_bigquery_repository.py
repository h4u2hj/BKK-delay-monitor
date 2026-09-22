from datetime import datetime, timedelta, timezone

from bkk_delays.bigquery_repository import (
    DASHBOARD_VIEW,
    BigQueryRepository,
    BigQueryStatistics,
    DelayCategoryBreakdown,
    HourlyDelayTrend,
    KpiSummary,
    MORICZ_UJBUDA_HEADSIGN,
    StopDelayRanking,
    TimePeriodDelayMatrix,
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
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        use_postgres=False,
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


def test_load_statistics_reads_dashboard_view_sections():
    client = FakeBigQueryClient(
        query_results=[
            [
                {
                    "avg_delay_minutes": 2.35,
                    "max_delay_minutes": 9.1,
                    "observation_count": 100,
                    "delayed_ratio": 0.42,
                    "significant_or_severe_count": 12,
                }
            ],
            [
                {
                    "stop_name": "Oktogon M",
                    "headsign": "Ujbuda-kozpont M",
                    "avg_delay_minutes": 4.2,
                    "significant_or_severe_count": 5,
                    "observation_count": 25,
                }
            ],
            [
                {
                    "calendar_date": "2026-05-16",
                    "route_number": "4",
                    "avg_delay_minutes": 2.8,
                    "observation_count": 50,
                }
            ],
            [
                {
                    "observed_hour": 0,
                    "avg_delay_minutes": 1.2,
                    "observation_count": 10,
                },
                {
                    "observed_hour": 0,
                    "avg_delay_minutes": 2.2,
                    "observation_count": 5,
                },
                {
                    "observed_hour": 23,
                    "avg_delay_minutes": 3.1,
                    "observation_count": 4,
                },
            ],
            [{"delay_category": "minor delay", "observation_count": 70}],
            [
                {
                    "route_number": "6",
                    "time_period": "afternoon peak",
                    "avg_delay_minutes": 3.4,
                    "observation_count": 40,
                }
            ],
        ]
    )
    repository = BigQueryRepository(_config(use_bigquery=True), client=client)

    stats = repository.load_statistics()

    assert stats.kpi_summary == KpiSummary(2.35, 9.1, 100, 0.42, 12)
    assert stats.stop_delay_ranking == (
        StopDelayRanking("Oktogon M", "Ujbuda-kozpont M", 4.2, 5, 25),
    )
    assert stats.delay_category_breakdown == (
        DelayCategoryBreakdown("minor delay", 70),
    )
    assert len(stats.hourly_delay_trend) == 24
    assert [row.observed_hour for row in stats.hourly_delay_trend] == list(range(24))
    assert stats.hourly_delay_trend[0] == HourlyDelayTrend(0, 1.53, 15)
    assert stats.hourly_delay_trend[23] == HourlyDelayTrend(23, 3.1, 4)
    assert stats.time_period_delay_matrix == (
        TimePeriodDelayMatrix("6", "afternoon peak", 3.4, 40),
    )
    assert len(client.queries) == 6
    assert all(
        f"`test-project.bkk_analytics.{DASHBOARD_VIEW}`" in query
        for query in client.queries
    )
    assert all("delay_observations" not in query for query in client.queries)
    assert not any("route comparison" in query.lower() for query in client.queries)


def test_bigquery_sql_queries_are_loaded_from_sql_file():
    queries = load_named_sql_queries()

    assert set(queries) == {
        "kpi_summary",
        "stop_delay_ranking",
        "daily_delay_trend",
        "hourly_delay_trend",
        "delay_category_breakdown",
        "time_period_delay_matrix",
    }
    assert "route_comparison" not in queries
    assert "{dashboard_view}" in queries["kpi_summary"]
    assert "SAFE_DIVIDE(SUM(delayed_count), SUM(observation_count))" in queries[
        "kpi_summary"
    ]
    assert "GENERATE_ARRAY(0, 23)" in queries["hourly_delay_trend"]
    assert "observed_hour" in queries["hourly_delay_trend"]
    assert "route_number" not in queries["hourly_delay_trend"]
    assert "LIMIT 15" in queries["stop_delay_ranking"]
    assert "delay_observations" not in "\n".join(queries.values())
    assert "routes" not in "\n".join(queries.values())
    assert "stops" not in "\n".join(queries.values())


def test_statistics_from_observations_builds_sample_analytics():
    stats = statistics_from_observations(
        _batch().delay_observations,
        _batch().stops,
    )

    assert isinstance(stats, BigQueryStatistics)
    assert stats.kpi_summary is not None
    assert stats.kpi_summary.observation_count == 1
    assert stats.stop_delay_ranking[0].stop_name == "Oktogon M"
    assert stats.stop_delay_ranking[0].headsign == MORICZ_UJBUDA_HEADSIGN
    assert stats.daily_delay_trend[0].route_number == "4"
    assert len(stats.hourly_delay_trend) == 24
    assert stats.hourly_delay_trend[0].observed_hour == 0
    assert stats.hourly_delay_trend[-1].observed_hour == 23
    assert stats.delay_category_breakdown[0].delay_category == "on time"


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

    assert [row.headsign for row in stats.stop_delay_ranking] == [
        "Szell Kalman ter M",
        MORICZ_UJBUDA_HEADSIGN,
    ]
    assert [row.stop_name for row in stats.stop_delay_ranking] == [
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
        headsign="Moricz Zsigmond korter M",
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

    assert len(stats.stop_delay_ranking) == 1
    assert stats.stop_delay_ranking[0].headsign == MORICZ_UJBUDA_HEADSIGN
    assert stats.stop_delay_ranking[0].observation_count == 2


def test_statistics_from_observations_groups_time_period_matrix():
    batch = _batch()
    observation = batch.delay_observations[0]
    morning_departure = observation.scheduled_departure.replace(hour=5)
    afternoon_departure = observation.scheduled_departure.replace(hour=13)
    later_observation = DelayObservation(
        id="OBS_2",
        collection_run_id=observation.collection_run_id,
        route_id="BKK_3060",
        stop_id=observation.stop_id,
        trip_id="BKK_TRIP_2",
        headsign=observation.headsign,
        direction_id=observation.direction_id,
        stop_sequence=observation.stop_sequence,
        scheduled_departure=afternoon_departure,
        predicted_departure=afternoon_departure + timedelta(minutes=2),
        delay_seconds=120,
        delay_category="minor_delay",
        created_at=observation.created_at,
    )
    morning_observation = DelayObservation(
        id=observation.id,
        collection_run_id=observation.collection_run_id,
        route_id=observation.route_id,
        stop_id=observation.stop_id,
        trip_id=observation.trip_id,
        headsign=observation.headsign,
        direction_id=observation.direction_id,
        stop_sequence=observation.stop_sequence,
        scheduled_departure=morning_departure,
        predicted_departure=morning_departure,
        delay_seconds=observation.delay_seconds,
        delay_category=observation.delay_category,
        created_at=observation.created_at,
    )

    stats = statistics_from_observations(
        (morning_observation, later_observation),
        batch.stops,
    )

    assert [row.time_period for row in stats.time_period_delay_matrix] == [
        "morning peak",
        "afternoon peak",
    ]
    assert stats.time_period_columns == ("morning peak", "afternoon peak")
    assert stats.time_period_value("6", "afternoon peak").avg_delay_minutes == 2.0


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
