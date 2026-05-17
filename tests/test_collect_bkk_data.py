from datetime import datetime, timezone

from bkk_delays.collect_bkk_data import run_collection
from bkk_delays.config import AppConfig
from bkk_delays.firestore_repository import FirestoreSaveSummary
from bkk_delays.models import (
    CollectionRun,
    DelayObservation,
    MonitoredStop,
    Route,
    SearchCollectionBatch,
    Stop,
)


def _config() -> AppConfig:
    return AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="test-project",
        firestore_database_id="",
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        use_firestore=True,
        use_bigquery=False,
        use_sample_data=False,
    )


def _batch(stop_id: str) -> SearchCollectionBatch:
    now = datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc)
    return SearchCollectionBatch(
        routes=(Route(id="BKK_ROUTE_4", short_name="4", route_type="TRAM"),),
        stops=(Stop(id=stop_id, name="Oktogon M", lat=None, lon=None),),
        collection_run=CollectionRun(
            id=f"RUN_{stop_id}",
            started_at=now,
            finished_at=now,
            status="success",
            records_saved=1,
        ),
        delay_observations=(
            DelayObservation(
                id=f"OBS_{stop_id}",
                collection_run_id=f"RUN_{stop_id}",
                route_id="BKK_ROUTE_4",
                stop_id=stop_id,
                trip_id=f"TRIP_{stop_id}",
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


def test_run_collection_calls_every_monitored_stop_with_limit_four():
    class FakeBkkClient:
        def __init__(self):
            self.calls = []

        def get_stop_departures(self, stop_id, limit=10):
            self.calls.append((stop_id, limit))
            return _batch(stop_id)

    class FakeFirestoreRepository:
        def __init__(self):
            self.saved_batches = []

        def save_search_collection_batch(self, batch):
            self.saved_batches.append(batch)
            return FirestoreSaveSummary(
                enabled=True,
                routes_saved=1,
                stops_saved=1,
                collection_runs_saved=1,
                delay_observations_saved=len(batch.delay_observations),
            )

    bkk_client = FakeBkkClient()
    repository = FakeFirestoreRepository()
    monitored_stops = (
        MonitoredStop("BKK_STOP_1", "First", ("4",), "direction"),
        MonitoredStop("BKK_STOP_2", "Second", ("6",), "direction"),
        MonitoredStop("BKK_STOP_1", "First duplicate", ("4",), "direction"),
    )

    summary = run_collection(
        config=_config(),
        bkk_client=bkk_client,
        firestore_repository=repository,
        monitored_stops=monitored_stops,
    )

    assert bkk_client.calls == [
        ("BKK_STOP_1", 4),
        ("BKK_STOP_2", 4),
        ("BKK_STOP_1", 4),
    ]
    assert len(repository.saved_batches) == 3
    assert summary.stops_requested == 3
    assert summary.api_calls_succeeded == 3
    assert summary.api_calls_failed == 0
    assert summary.observations_generated == 3
    assert summary.observations_saved == 3
    assert summary.status == "success"


def test_run_collection_continues_after_stop_failure():
    class FakeBkkClient:
        def get_stop_departures(self, stop_id, limit=10):
            if stop_id == "BKK_BAD_STOP":
                raise RuntimeError("boom")
            return _batch(stop_id)

    class FakeFirestoreRepository:
        def save_search_collection_batch(self, batch):
            return FirestoreSaveSummary(
                enabled=True,
                delay_observations_saved=len(batch.delay_observations),
            )

    summary = run_collection(
        config=_config(),
        bkk_client=FakeBkkClient(),
        firestore_repository=FakeFirestoreRepository(),
        monitored_stops=(
            MonitoredStop("BKK_BAD_STOP", "Bad", ("4",), "direction"),
            MonitoredStop("BKK_GOOD_STOP", "Good", ("4",), "direction"),
        ),
    )

    assert summary.status == "partial_success"
    assert summary.api_calls_succeeded == 1
    assert summary.api_calls_failed == 1
    assert summary.errors[0].stop_id == "BKK_BAD_STOP"
