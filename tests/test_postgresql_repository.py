from datetime import datetime, timezone

import pytest

from bkk_delays.config import AppConfig
from bkk_delays.models import CollectionRun, DelayObservation, Route, SearchCollectionBatch, Stop
from bkk_delays.postgresql_repository import (
    PostgreSQLHistoryEntry,
    PostgreSQLRepository,
    PostgreSQLRepositoryError,
    _history_entry_from_row,
)


def _config(use_postgres: bool) -> AppConfig:
    return AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="test-project",
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        use_postgres=use_postgres,
        use_bigquery=False,
        postgres_host="127.0.0.1",
        postgres_db="bkk-db",
        postgres_user="bkk_user",
        postgres_password="secret",
        postgres_schema="transit_data",
    )


def _batch() -> SearchCollectionBatch:
    now = datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc)
    return SearchCollectionBatch(
        routes=(Route(id="BKK_ROUTE_4", short_name="4", route_type="TRAM"),),
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
                route_id="BKK_ROUTE_4",
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


def test_disabled_postgresql_repository_is_noop():
    repository = PostgreSQLRepository(_config(use_postgres=False))

    summary = repository.save_search_collection_batch(_batch())

    assert not summary.enabled
    assert summary.total_saved == 0
    assert repository.list_recent_history_entries() == []


def test_postgresql_repository_upserts_batch_and_skips_duplicate_observations():
    connection = FakeConnection(existing_duplicate_keys={
        "BKK_TRIP_1|BKK_STOP_1|2026-05-16T14:00:00+00:00"
    })
    repository = PostgreSQLRepository(
        _config(use_postgres=True),
        connection_factory=lambda: connection,
    )

    summary = repository.save_search_collection_batch(_batch())

    assert summary.enabled
    assert summary.routes_saved == 1
    assert summary.stops_saved == 1
    assert summary.collection_runs_saved == 1
    assert summary.delay_observations_saved == 0
    assert summary.duplicate_observations_skipped == 1
    assert any(
        "ON CONFLICT (duplicate_key) DO NOTHING" in query
        for query, _params in connection.cursor_instance.executed
    )


def test_postgresql_repository_inserts_new_observation():
    connection = FakeConnection()
    repository = PostgreSQLRepository(
        _config(use_postgres=True),
        connection_factory=lambda: connection,
    )

    summary = repository.save_search_collection_batch(_batch())

    assert summary.delay_observations_saved == 1
    assert summary.duplicate_observations_skipped == 0


def test_history_entry_is_constructed_from_postgresql_row():
    row = (
        "Oktogon M",
        "4",
        "Ujbuda-kozpont M",
        datetime(2026, 5, 16, 12, 5, tzinfo=timezone.utc),
        datetime(2026, 5, 16, 12, 7, tzinfo=timezone.utc),
        120,
    )

    entry = _history_entry_from_row(row)

    assert entry == PostgreSQLHistoryEntry(
        station_name="Oktogon M",
        route_short_name="4",
        destination_name="Ujbuda-kozpont M",
        expected_departure="14:05",
        realtime_departure="14:07",
        delay_seconds="120",
    )


def test_postgresql_repository_reports_missing_required_settings():
    config = AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="test-project",
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        use_postgres=True,
        use_bigquery=False,
    )
    repository = PostgreSQLRepository(config)

    with pytest.raises(PostgreSQLRepositoryError, match="POSTGRES_HOST"):
        repository.save_search_collection_batch(_batch())


class FakeConnection:
    def __init__(self, existing_duplicate_keys=None):
        self.cursor_instance = FakeCursor(existing_duplicate_keys or set())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def cursor(self):
        return self.cursor_instance


class FakeCursor:
    def __init__(self, existing_duplicate_keys):
        self.existing_duplicate_keys = existing_duplicate_keys
        self.executed = []
        self.next_fetchone = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        query_text = str(query)
        self.executed.append((query_text, params))
        if "INSERT INTO delay_observations" not in query_text:
            return

        duplicate_key = params[-1]
        if duplicate_key in self.existing_duplicate_keys:
            self.next_fetchone = None
        else:
            self.existing_duplicate_keys.add(duplicate_key)
            self.next_fetchone = (params[0],)

    def fetchone(self):
        value = self.next_fetchone
        self.next_fetchone = None
        return value

    def fetchall(self):
        return []
