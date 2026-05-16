from datetime import datetime, timezone

import pytest
from google.auth.exceptions import DefaultCredentialsError

from bkk_delays.config import AppConfig
from bkk_delays.firestore_repository import (
    COLLECTION_RUNS_COLLECTION,
    DELAY_OBSERVATIONS_COLLECTION,
    ROUTES_COLLECTION,
    STOPS_COLLECTION,
    FirestoreHistoryEntry,
    FirestoreRepository,
    FirestoreRepositoryError,
    _history_entry_from_observation_snapshot,
    search_collection_batch_to_firestore_documents,
)
from bkk_delays.models import CollectionRun, DelayObservation, Route, SearchCollectionBatch, Stop


def _config(use_firestore: bool) -> AppConfig:
    return AppConfig(
        bkk_api_key="test-key",
        bkk_api_base_url="https://example.test",
        gcp_project_id="test-project",
        firestore_database_id="",
        bigquery_dataset="bkk_analytics",
        bigquery_table="delay_observations",
        google_application_credentials="",
        use_firestore=use_firestore,
        use_bigquery=False,
        use_sample_data=True,
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


def test_search_collection_batch_to_firestore_documents_uses_target_schema():
    documents = search_collection_batch_to_firestore_documents(_batch())

    assert documents[ROUTES_COLLECTION]["BKK_ROUTE_4"] == {
        "id": "BKK_ROUTE_4",
        "short_name": "4",
        "route_type": "TRAM",
    }
    assert documents[STOPS_COLLECTION]["BKK_STOP_1"]["name"] == "Oktogon M"
    assert documents[COLLECTION_RUNS_COLLECTION]["RUN_1"]["records_saved"] == 1
    observation = documents[DELAY_OBSERVATIONS_COLLECTION]["OBS_1"]
    assert observation["collection_run_id"] == "RUN_1"
    assert observation["route_id"] == "BKK_ROUTE_4"
    assert observation["stop_id"] == "BKK_STOP_1"
    assert observation["delay_category"] == "on_time"
    assert observation["duplicate_key"] == (
        "BKK_TRIP_1|BKK_STOP_1|2026-05-16T14:00:00+00:00|"
        "2026-05-16T14:00:00+00:00"
    )


def test_disabled_firestore_repository_is_noop():
    repository = FirestoreRepository(_config(use_firestore=False))

    summary = repository.save_search_collection_batch(_batch())

    assert summary.enabled is False
    assert summary.total_saved == 0


def test_firestore_repository_uploads_each_batch_entry_with_merge():
    client = FakeFirestoreClient()
    repository = FirestoreRepository(_config(use_firestore=True), client=client)

    summary = repository.save_search_collection_batch(_batch())

    assert summary.enabled is True
    assert summary.total_saved == 4
    assert client.committed_writes == [
        ("routes", "BKK_ROUTE_4", True),
        ("stops", "BKK_STOP_1", True),
        ("collection_runs", "RUN_1", True),
        ("delay_observations", "OBS_1", True),
    ]


def test_firestore_repository_skips_duplicate_delay_observation_by_trip_and_stop():
    client = FakeFirestoreClient(
        documents={
            DELAY_OBSERVATIONS_COLLECTION: {
                "OBS_1": {
                    "trip_id": "BKK_TRIP_1",
                    "stop_id": "BKK_STOP_1",
                },
            },
        }
    )
    repository = FirestoreRepository(_config(use_firestore=True), client=client)

    summary = repository.save_search_collection_batch(_batch())

    assert summary.delay_observations_saved == 0
    assert summary.duplicate_observations_skipped == 1
    assert client.committed_writes == [
        ("routes", "BKK_ROUTE_4", True),
        ("stops", "BKK_STOP_1", True),
        ("collection_runs", "RUN_1", True),
    ]


def test_firestore_repository_does_not_treat_same_trip_at_different_stop_as_duplicate():
    client = FakeFirestoreClient(
        documents={
            DELAY_OBSERVATIONS_COLLECTION: {
                "EXISTING_OBS": {
                    "trip_id": "BKK_TRIP_1",
                    "stop_id": "BKK_OTHER_STOP",
                },
            },
        }
    )
    repository = FirestoreRepository(_config(use_firestore=True), client=client)

    assert repository.delay_observation_duplicate_exists(
        _batch().delay_observations[0]
    ) is False


def test_history_entry_is_constructed_from_firestore_documents():
    firestore_time = datetime(2026, 5, 16, 12, 5, tzinfo=timezone.utc)
    client = FakeFirestoreClient(
        documents={
            STOPS_COLLECTION: {
                "BKK_STOP_1": {"name": "Oktogon M"},
            },
            ROUTES_COLLECTION: {
                "BKK_ROUTE_4": {"short_name": "4"},
            },
        }
    )
    observation_snapshot = FakeDocumentSnapshot(
        {
            "stop_id": "BKK_STOP_1",
            "route_id": "BKK_ROUTE_4",
            "headsign": "Ujbuda-kozpont M",
            "scheduled_departure": firestore_time,
            "predicted_departure": firestore_time,
            "delay_seconds": 0,
        }
    )

    entry = _history_entry_from_observation_snapshot(
        client,
        transaction=object(),
        observation_snapshot=observation_snapshot,
    )

    assert entry == FirestoreHistoryEntry(
        station_name="Oktogon M",
        route_short_name="4",
        destination_name="Ujbuda-kozpont M",
        expected_departure="14:05",
        realtime_departure="14:05",
        delay_seconds="0",
    )


def test_firestore_repository_reports_missing_adc_without_startup_traceback(
    monkeypatch,
    caplog,
):
    def fail_to_build_client(config):
        raise DefaultCredentialsError("missing ADC")

    monkeypatch.setattr(
        "bkk_delays.firestore_repository._build_firestore_client",
        fail_to_build_client,
    )

    with caplog.at_level("WARNING", logger="bkk_delays.firestore_repository"):
        repository = FirestoreRepository(_config(use_firestore=True))

    with pytest.raises(FirestoreRepositoryError, match="Application Default Credentials"):
        repository.save_search_collection_batch(_batch())

    assert "initialization skipped" in caplog.text
    assert "Firestore client initialization failed" not in caplog.text


class FakeFirestoreClient:
    def __init__(self, documents=None):
        self.committed_writes = []
        self.documents = documents or {}

    def transaction(self):
        return FakeFirestoreTransaction(self)

    def batch(self):
        return FakeFirestoreBatch(self)

    def collection(self, name):
        return FakeCollectionReference(self, name)


class FakeFirestoreTransaction:
    def __init__(self, client):
        self.client = client
        self.writes = []
        self._id = None
        self._max_attempts = 1
        self._read_only = False

    def _clean_up(self):
        self.writes = []

    def _begin(self, retry_id=None):
        self._id = retry_id or b"fake-transaction-id"

    def _commit(self):
        self.client.committed_writes.extend(self.writes)

    def _rollback(self):
        self.writes = []

    def set(self, document_ref, document, merge=False):
        self.writes.append((document_ref.collection_name, document_ref.document_id, merge))


class FakeFirestoreBatch:
    def __init__(self, client):
        self.client = client
        self.writes = []

    def set(self, document_ref, document, merge=False):
        self.writes.append((document_ref.collection_name, document_ref.document_id, merge))

    def commit(self):
        self.client.committed_writes.extend(self.writes)


class FakeCollectionReference:
    def __init__(self, client, collection_name):
        self.client = client
        self.collection_name = collection_name

    def document(self, document_id):
        return FakeDocumentReference(self.client, self.collection_name, document_id)

    def where(self, field_name, operation, value):
        return FakeQuery(self.client, self.collection_name).where(
            field_name,
            operation,
            value,
        )


class FakeDocumentReference:
    def __init__(self, client, collection_name, document_id):
        self.client = client
        self.collection_name = collection_name
        self.document_id = document_id

    def get(self, transaction=None):
        document = self.client.documents.get(self.collection_name, {}).get(
            self.document_id
        )
        return FakeDocumentSnapshot(document, exists=document is not None)


class FakeDocumentSnapshot:
    def __init__(self, document, exists=True):
        self.document = document
        self.exists = exists

    def to_dict(self):
        return self.document


class FakeQuery:
    def __init__(self, client, collection_name, filters=None, limit_count=None):
        self.client = client
        self.collection_name = collection_name
        self.filters = filters or []
        self.limit_count = limit_count

    def where(self, field_name, operation, value):
        return FakeQuery(
            self.client,
            self.collection_name,
            [*self.filters, (field_name, operation, value)],
            self.limit_count,
        )

    def limit(self, count):
        return FakeQuery(
            self.client,
            self.collection_name,
            self.filters,
            count,
        )

    def stream(self, transaction=None):
        documents = self.client.documents.get(self.collection_name, {})
        matches = []
        for document in documents.values():
            if all(
                operation == "==" and document.get(field_name) == value
                for field_name, operation, value in self.filters
            ):
                matches.append(FakeDocumentSnapshot(document))

        if self.limit_count is not None:
            matches = matches[: self.limit_count]

        return iter(matches)
