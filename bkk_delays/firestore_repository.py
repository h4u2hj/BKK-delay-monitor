"""Firestore persistence for normalized BKK delay entities."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from bkk_delays.config import AppConfig
from bkk_delays.delay_processor import create_observation_duplicate_key
from bkk_delays.models import (
    CollectionRun,
    DelayObservation,
    Route,
    SearchCollectionBatch,
    Stop,
)

LOGGER = logging.getLogger(__name__)

ROUTES_COLLECTION = "routes"
STOPS_COLLECTION = "stops"
COLLECTION_RUNS_COLLECTION = "collection_runs"
DELAY_OBSERVATIONS_COLLECTION = "delay_observations"
DISPLAY_TIMEZONE = ZoneInfo("Europe/Budapest")


class FirestoreRepositoryError(RuntimeError):
    """Raised when Firestore persistence is enabled but cannot complete."""


@dataclass(frozen=True)
class FirestoreSaveSummary:
    enabled: bool
    routes_saved: int = 0
    stops_saved: int = 0
    collection_runs_saved: int = 0
    delay_observations_saved: int = 0
    duplicate_observations_skipped: int = 0

    @property
    def total_saved(self) -> int:
        return (
                self.routes_saved
                + self.stops_saved
                + self.collection_runs_saved
                + self.delay_observations_saved
        )


@dataclass(frozen=True)
class FirestoreHistoryEntry:
    station_name: str
    route_short_name: str
    destination_name: str
    expected_departure: str
    realtime_departure: str
    delay_seconds: str


FirestoreDocumentBatch = dict[str, dict[str, dict[str, Any]]]


class FirestoreRepository:
    """Save database-ready entity batches to Firestore collections."""

    def __init__(
            self,
            config: AppConfig,
            client: Optional[Any] = None,
            batch_write_limit: int = 450,
    ) -> None:
        self.config = config
        self._client = client
        self._batch_write_limit = batch_write_limit
        self._init_error = ""

        if self.config.use_firestore and self._client is None:
            try:
                self._client = _build_firestore_client(config)
            except Exception as exc:
                self._init_error = _format_firestore_init_error(exc)
                LOGGER.warning(
                    "Firestore client initialization skipped: %s",
                    self._init_error,
                )

    def save_search_collection_batch(
            self,
            batch: SearchCollectionBatch,
    ) -> FirestoreSaveSummary:
        """Upload every normalized entity in a search collection batch."""

        if not self.config.use_firestore:
            return FirestoreSaveSummary(enabled=False)

        client = self._require_client()
        try:
            counts = _save_search_collection_batch_transactionally(
                client,
                batch,
                timeout=self.config.firestore_timeout_seconds,
            )
        except Exception as exc:
            raise FirestoreRepositoryError(
                f"Firestore batch upload failed: {exc}"
            ) from exc

        LOGGER.info(
            "Saved Firestore batch: %s routes, %s stops, %s collection runs, "
            "%s delay observations, %s duplicates skipped.",
            counts.routes_saved,
            counts.stops_saved,
            counts.collection_runs_saved,
            counts.delay_observations_saved,
            counts.duplicate_observations_skipped,
        )
        return counts

    def delay_observation_duplicate_exists(
            self,
            observation: DelayObservation,
    ) -> bool:
        """Return true when the natural duplicate key already exists."""

        if not self.config.use_firestore:
            return False

        client = self._require_client()
        return _delay_observation_duplicate_exists(
            client,
            observation,
            timeout=self.config.firestore_timeout_seconds,
        )

    def list_recent_history_entries(
            self,
            limit: int = 50,
    ) -> list[FirestoreHistoryEntry]:
        """Read recent observations from Firestore and join route/stop documents."""

        if not self.config.use_firestore:
            return []

        client = self._require_client()
        try:
            return _read_history_entries(
                client,
                limit=limit,
                timeout=self.config.firestore_timeout_seconds,
            )
        except Exception as exc:
            raise FirestoreRepositoryError(
                f"Firestore history read failed: {exc}"
            ) from exc

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client

        message = self._init_error or "Firestore client is not configured."
        raise FirestoreRepositoryError(message)


def search_collection_batch_to_firestore_documents(
        batch: SearchCollectionBatch,
) -> FirestoreDocumentBatch:
    """Convert a normalized search batch into Firestore collection documents."""

    return {
        ROUTES_COLLECTION: {
            route.id: route_to_firestore_document(route) for route in batch.routes
        },
        STOPS_COLLECTION: {
            stop.id: stop_to_firestore_document(stop) for stop in batch.stops
        },
        COLLECTION_RUNS_COLLECTION: {
            batch.collection_run.id: collection_run_to_firestore_document(
                batch.collection_run
            )
        },
        DELAY_OBSERVATIONS_COLLECTION: {
            observation.id: delay_observation_to_firestore_document(observation)
            for observation in batch.delay_observations
        },
    }


def route_to_firestore_document(route: Route) -> dict[str, Any]:
    return {
        "id": route.id,
        "short_name": route.short_name,
        "route_type": route.route_type,
    }


def stop_to_firestore_document(stop: Stop) -> dict[str, Any]:
    return {
        "id": stop.id,
        "name": stop.name,
        "lat": stop.lat,
        "lon": stop.lon,
    }


def collection_run_to_firestore_document(
        collection_run: CollectionRun,
) -> dict[str, Any]:
    return {
        "id": collection_run.id,
        "started_at": collection_run.started_at,
        "finished_at": collection_run.finished_at,
        "status": collection_run.status,
        "records_saved": collection_run.records_saved,
        "error_message": collection_run.error_message,
    }


def delay_observation_to_firestore_document(
        observation: DelayObservation,
) -> dict[str, Any]:
    return {
        "id": observation.id,
        "collection_run_id": observation.collection_run_id,
        "route_id": observation.route_id,
        "stop_id": observation.stop_id,
        "trip_id": observation.trip_id,
        "headsign": observation.headsign,
        "direction_id": observation.direction_id,
        "stop_sequence": observation.stop_sequence,
        "scheduled_departure": observation.scheduled_departure,
        "predicted_departure": observation.predicted_departure,
        "delay_seconds": observation.delay_seconds,
        "delay_category": observation.delay_category,
        "created_at": observation.created_at,
        "duplicate_key": create_observation_duplicate_key(
            observation.trip_id,
            observation.stop_id,
            observation.scheduled_departure,
        ),
    }


def _read_history_entries(
        client: Any,
        limit: int,
        timeout: float,
) -> list[FirestoreHistoryEntry]:
    observations = (
        client.collection(DELAY_OBSERVATIONS_COLLECTION)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream(timeout=timeout)
    )
    return [
        _history_entry_from_observation_snapshot(
            client,
            observation_snapshot,
            timeout=timeout,
        )
        for observation_snapshot in observations
    ]


def _history_entry_from_observation_snapshot(
        client: Any,
        observation_snapshot: Any,
        timeout: Optional[float] = None,
        transaction: Optional[Any] = None,
) -> FirestoreHistoryEntry:
    observation = observation_snapshot.to_dict() or {}
    stop_id = str(observation.get("stop_id") or "")
    route_id = str(observation.get("route_id") or "")

    stop = _document_data_in_transaction(
        client,
        STOPS_COLLECTION,
        stop_id,
        timeout=timeout,
        transaction=transaction,
    )
    route = _document_data_in_transaction(
        client,
        ROUTES_COLLECTION,
        route_id,
        timeout=timeout,
        transaction=transaction,
    )

    return FirestoreHistoryEntry(
        station_name=str(stop.get("name") or stop_id or "-"),
        route_short_name=str(route.get("short_name") or route_id or "-"),
        destination_name=str(observation.get("headsign") or "-"),
        expected_departure=_format_history_time(observation.get("scheduled_departure")),
        realtime_departure=_format_history_time(observation.get("predicted_departure")),
        delay_seconds=str(observation.get("delay_seconds") or 0),
    )


def _document_data_in_transaction(
        client: Any,
        collection_name: str,
        document_id: str,
        timeout: Optional[float] = None,
        transaction: Optional[Any] = None,
) -> dict[str, Any]:
    if not document_id:
        return {}

    snapshot = (
        client.collection(collection_name)
        .document(document_id)
        .get(transaction=transaction, timeout=timeout)
    )
    if not getattr(snapshot, "exists", True):
        return {}

    return snapshot.to_dict() or {}


def _format_history_time(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(DISPLAY_TIMEZONE).strftime("%H:%M")
    return "-"


def _delay_observation_duplicate_exists(
        client: Any,
        observation: DelayObservation,
        transaction: Optional[Any] = None,
        timeout: Optional[float] = None,
) -> bool:
    duplicate_key = _observation_duplicate_key(observation)
    if not duplicate_key:
        return False

    snapshots = (
        client.collection(DELAY_OBSERVATIONS_COLLECTION)
        .where("duplicate_key", "==", duplicate_key)
        .limit(1)
        .stream(transaction=transaction, timeout=timeout)
    )

    if any(getattr(snapshot, "exists", True) for snapshot in snapshots):
        return True

    return _legacy_observation_duplicate_exists(
        client,
        observation,
        transaction=transaction,
        timeout=timeout,
    )


def _observation_duplicate_key(observation: DelayObservation) -> str:
    return create_observation_duplicate_key(
        observation.trip_id,
        observation.stop_id,
        observation.scheduled_departure,
    )


def _legacy_observation_duplicate_exists(
        client: Any,
        observation: DelayObservation,
        transaction: Optional[Any] = None,
        timeout: Optional[float] = None,
) -> bool:
    snapshots = (
        client.collection(DELAY_OBSERVATIONS_COLLECTION)
        .where("trip_id", "==", observation.trip_id)
        .stream(transaction=transaction, timeout=timeout)
    )

    return any(
        getattr(snapshot, "exists", True)
        and _same_trip_stop_departure(snapshot.to_dict() or {}, observation)
        for snapshot in snapshots
    )


def _same_trip_stop_departure(
        document: dict[str, Any],
        observation: DelayObservation,
) -> bool:
    return (
        document.get("stop_id") == observation.stop_id
        and document.get("scheduled_departure") == observation.scheduled_departure
    )


def _save_search_collection_batch_transactionally(
        client: Any,
        batch: SearchCollectionBatch,
        timeout: float,
) -> FirestoreSaveSummary:
    transaction = client.transaction()

    @firestore.transactional
    def save_in_transaction(transaction: Any) -> FirestoreSaveSummary:
        new_observations = [
            observation
            for observation in batch.delay_observations
            if not _delay_observation_duplicate_exists(
                client,
                observation,
                transaction=transaction,
                timeout=timeout,
            )
        ]
        duplicate_observations_skipped = len(batch.delay_observations) - len(
            new_observations
        )
        documents = search_collection_batch_to_firestore_documents(
            SearchCollectionBatch(
                routes=batch.routes,
                stops=batch.stops,
                collection_run=replace(
                    batch.collection_run,
                    records_saved=len(new_observations),
                ),
                delay_observations=tuple(new_observations),
            ),
        )
        counts = _document_counts(
            documents,
            duplicate_observations_skipped=duplicate_observations_skipped,
        )

        for collection_name, collection_documents in documents.items():
            for document_id, document in collection_documents.items():
                document_ref = client.collection(collection_name).document(document_id)
                transaction.set(document_ref, document, merge=True)

        return counts

    return save_in_transaction(transaction)


def _document_counts(
        documents: FirestoreDocumentBatch,
        duplicate_observations_skipped: int = 0,
) -> FirestoreSaveSummary:
    return FirestoreSaveSummary(
        enabled=True,
        routes_saved=len(documents[ROUTES_COLLECTION]),
        stops_saved=len(documents[STOPS_COLLECTION]),
        collection_runs_saved=len(documents[COLLECTION_RUNS_COLLECTION]),
        delay_observations_saved=len(documents[DELAY_OBSERVATIONS_COLLECTION]),
        duplicate_observations_skipped=duplicate_observations_skipped,
    )


def _build_firestore_client(config: AppConfig) -> Any:
    credentials = _load_service_account_credentials(config)
    client_kwargs = {"project": config.gcp_project_id or None}
    if credentials is not None:
        client_kwargs["credentials"] = credentials

    if config.firestore_database_id:
        try:
            return firestore.Client(
                **client_kwargs,
                database=config.firestore_database_id,
            )
        except TypeError:
            LOGGER.warning(
                "Installed google-cloud-firestore does not accept database=; "
                "falling back to the default Firestore database."
            )

    return firestore.Client(**client_kwargs)


def _format_firestore_init_error(exc: Exception) -> str:
    if exc.__class__.__name__ == "DefaultCredentialsError":
        return f"Application Default Credentials are missing or unavailable: {exc}"
    return str(exc)


def _load_service_account_credentials(config: AppConfig) -> Any:
    """Load an explicit service account JSON file when configured."""

    if not config.google_application_credentials:
        return None

    credentials_path = Path(config.google_application_credentials).expanduser()
    if not credentials_path.is_file():
        raise FirestoreRepositoryError(
            "GOOGLE_APPLICATION_CREDENTIALS points to a file that does not exist: "
            f"{credentials_path}"
        )

    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise FirestoreRepositoryError(
            "google-auth is required to load GOOGLE_APPLICATION_CREDENTIALS."
        ) from exc

    return service_account.Credentials.from_service_account_file(
        str(credentials_path),
    )
