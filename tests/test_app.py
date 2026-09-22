from dataclasses import replace
from datetime import datetime, timezone

from bkk_delays.app import create_app
from bkk_delays.bigquery_repository import (
    BigQueryStatistics,
    DailyDelayTrend,
    DelayCategoryBreakdown,
    HourlyDelayTrend,
    KpiSummary,
    StopDelayRanking,
    TimePeriodDelayMatrix,
)
from bkk_delays.config import AppConfig
from bkk_delays.models import (
    CollectionRun,
    DelayObservation,
    Route,
    SearchCollectionBatch,
    StationSearchResult,
    Stop,
)
from bkk_delays.postgresql_repository import PostgreSQLHistoryEntry


def _test_config() -> AppConfig:
    return AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="",
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        use_postgres=False,
        use_bigquery=False,
    )


def test_index_page_renders_search_ui():
    client = create_app(config=_test_config()).test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Find a BKK station" in html
    assert "Search for a station..." in html
    assert 'name="station_id"' in html
    assert 'id="station-results"' in html
    assert "Get" in html


def test_history_page_renders_empty_state():
    client = create_app(config=_test_config()).test_client()

    response = client.get("/history")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Stored observations" in html
    assert "No history yet" in html


def test_statistics_page_renders_empty_state_without_bigquery_data():
    client = create_app(config=_test_config()).test_client()

    response = client.get("/statistics")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "4-6 statistics" in html
    assert "BigQuery is disabled" in html
    assert "No statistics yet" in html


def test_statistics_page_renders_bigquery_statistics():
    class FakeBigQueryRepository:
        def load_statistics(self):
            return BigQueryStatistics(
                kpi_summary=KpiSummary(
                    avg_delay_minutes=2.25,
                    max_delay_minutes=8.0,
                    observation_count=20,
                    delayed_ratio=0.8,
                    significant_or_severe_count=4,
                ),
                stop_delay_ranking=(
                    StopDelayRanking(
                        "Oktogon M",
                        "Ujbuda-kozpont M",
                        3.5,
                        2,
                        10,
                    ),
                ),
                daily_delay_trend=(
                    DailyDelayTrend(
                        datetime(2026, 5, 16, tzinfo=timezone.utc).date(),
                        "4",
                        2.1,
                        12,
                    ),
                ),
                hourly_delay_trend=(
                    HourlyDelayTrend(0, 1.0, 3),
                    HourlyDelayTrend(0, 2.0, 1),
                    HourlyDelayTrend(23, 3.2, 5),
                ),
                delay_category_breakdown=(
                    DelayCategoryBreakdown("minor delay", 14),
                ),
                time_period_delay_matrix=(
                    TimePeriodDelayMatrix("4", "afternoon peak", 2.4, 8),
                ),
            )

    config = replace(_test_config(), use_bigquery=True)
    client = create_app(
        config=config,
        bigquery_repository=FakeBigQueryRepository(),
    ).test_client()

    response = client.get("/statistics")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "BigQuery analytics" in html
    assert "4-6 statistics" in html
    assert "Data refreshed every night" in html
    assert "Average delay" in html
    assert "Worst stops" in html
    assert "Daily delay trend" in html
    assert "Hourly delay trend" in html
    assert "Delay categories" in html
    assert "Time period matrix" in html
    assert "Predicted delay now" not in html
    assert "Route comparison" not in html
    assert "Delay by direction" not in html
    assert "Delay progression" not in html
    assert "Oktogon M" in html
    assert "Ujbuda-kozpont M" in html
    assert "2.25 min" in html
    assert "3.50 min" in html
    assert "00:00" in html
    assert "23:00" in html
    assert html.count("<td>00:00</td>") == 1
    assert html.count("<td>23:00</td>") == 1
    assert "minor delay" in html
    assert "afternoon peak" in html
    assert "80.0%" in html


def test_history_page_renders_postgresql_entries():
    class FakePostgreSQLRepository:
        def list_recent_history_entries(self, limit=50):
            assert limit == 50
            return [
                PostgreSQLHistoryEntry(
                    station_name="Oktogon M",
                    route_short_name="4",
                    destination_name="Ujbuda-kozpont M",
                    expected_departure="14:05",
                    realtime_departure="14:07",
                    delay_seconds="120",
                )
            ]

    client = create_app(
        config=_test_config(),
        postgresql_repository=FakePostgreSQLRepository(),
    ).test_client()

    response = client.get("/history")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Destination" in html
    assert "Expected departure" in html
    assert "Real-time departure" in html
    assert "Delay seconds" in html
    assert "Oktogon M" in html
    assert "Ujbuda-kozpont M" in html
    assert "14:05" in html
    assert "14:07" in html
    assert "120" in html


def test_station_search_requires_more_than_three_characters():
    client = create_app(config=_test_config()).test_client()

    response = client.get("/api/stations?q=Okt")

    assert response.status_code == 200
    assert response.get_json() == {"stations": []}


def test_station_search_returns_station_results():
    class FakeBkkClient:
        def search_stations(self, query):
            assert query == "Oktogon"
            return [
                StationSearchResult(
                    stop_id="BKK_TEST_STOP",
                    name="Oktogon M",
                    code="123456",
                    direction="Szell Kalman ter",
                )
            ]

    client = create_app(config=_test_config(), bkk_client=FakeBkkClient()).test_client()

    response = client.get("/api/stations?q=Oktogon")

    assert response.status_code == 200
    assert response.get_json() == {
        "stations": [
            {
                "id": "BKK_TEST_STOP",
                "name": "Oktogon M",
                "code": "123456",
                "direction": "Szell Kalman ter",
                "lat": None,
                "lon": None,
                "route_ids": [],
                "route_number": None,
            }
        ]
    }


def test_index_page_renders_selected_stop_departures():
    class FakePostgreSQLRepository:
        def __init__(self):
            self.saved_batches = []

        def save_search_collection_batch(self, batch):
            self.saved_batches.append(batch)

    class FakeBigQueryRepository:
        def save_search_collection_batch(self, batch):
            raise AssertionError("station search must not write to BigQuery")

    class FakeBkkClient:
        def get_stop_departures(self, stop_id, limit=8):
            assert stop_id == "BKK_TEST_STOP"
            assert limit == 3
            return SearchCollectionBatch(
                routes=(Route(id="BKK_ROUTE_4", short_name="4", route_type="TRAM"),),
                stops=(Stop(id="BKK_TEST_STOP", name="Oktogon M", lat=None, lon=None),),
                collection_run=CollectionRun(
                    id="RUN_1",
                    started_at=datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc),
                    finished_at=datetime(2026, 5, 16, 14, 0, 1, tzinfo=timezone.utc),
                    status="success",
                    records_saved=1,
                ),
                delay_observations=(
                    DelayObservation(
                        id="OBS_1",
                        collection_run_id="RUN_1",
                        route_id="BKK_ROUTE_4",
                        stop_id="BKK_TEST_STOP",
                        trip_id="BKK_TRIP_1",
                        headsign="Ujbuda-kozpont M",
                        direction_id="1",
                        stop_sequence=12,
                        scheduled_departure=datetime(
                            2026,
                            5,
                            16,
                            14,
                            5,
                            tzinfo=timezone.utc,
                        ),
                        predicted_departure=datetime(
                            2026,
                            5,
                            16,
                            14,
                            7,
                            tzinfo=timezone.utc,
                        ),
                        delay_seconds=120,
                        delay_category="minor_delay",
                        created_at=datetime(
                            2026,
                            5,
                            16,
                            14,
                            0,
                            1,
                            tzinfo=timezone.utc,
                        ),
                    ),
                ),
            )

    fake_repository = FakePostgreSQLRepository()
    client = create_app(
        config=replace(_test_config(), use_bigquery=True),
        bkk_client=FakeBkkClient(),
        postgresql_repository=fake_repository,
        bigquery_repository=FakeBigQueryRepository(),
    ).test_client()

    response = client.get("/?station=Oktogon%20M&station_id=BKK_TEST_STOP")

    assert response.status_code == 200
    assert len(fake_repository.saved_batches) == 1
    html = response.get_data(as_text=True)
    assert "Next departures" in html
    assert "Oktogon M" in html
    assert "Ujbuda-kozpont M" in html
    assert "14:05" in html
    assert "14:07" in html
    assert "Delay seconds" in html
    assert "120" in html
