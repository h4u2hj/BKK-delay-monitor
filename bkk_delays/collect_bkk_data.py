"""Scheduled collection workflow for monitored BKK stops."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional, Sequence

from bkk_delays.bkk_api import BkkApiClient
from bkk_delays.config import AppConfig, load_config
from bkk_delays.firestore_repository import (
    FirestoreRepository,
)
from bkk_delays.models import MONITORED_STOPS, MonitoredStop

DEFAULT_DEPARTURE_LIMIT = 4


@dataclass(frozen=True)
class CollectionError:
    stop_id: str
    stop_name: str
    message: str


@dataclass(frozen=True)
class CollectionSummary:
    stops_requested: int
    api_calls_succeeded: int
    api_calls_failed: int
    observations_generated: int
    observations_saved: int
    duplicate_observations_skipped: int
    errors: tuple[CollectionError, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if self.api_calls_failed and self.api_calls_succeeded:
            return "partial_success"
        if self.api_calls_failed:
            return "failed"
        return "success"

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {"status": self.status}


def run_collection(
        config: Optional[AppConfig] = None,
        bkk_client: Optional[BkkApiClient] = None,
        firestore_repository: Optional[FirestoreRepository] = None,
        monitored_stops: Sequence[MonitoredStop] = MONITORED_STOPS,
        departure_limit: int = DEFAULT_DEPARTURE_LIMIT,
) -> CollectionSummary:
    """Fetch departures for monitored stops and persist them to Firestore."""

    app_config = config or load_config()
    client = bkk_client or BkkApiClient(app_config)
    repository = firestore_repository or FirestoreRepository(app_config)

    api_calls_succeeded = 0
    api_calls_failed = 0
    observations_generated = 0
    observations_saved = 0
    duplicate_observations_skipped = 0
    errors: list[CollectionError] = []

    for stop in monitored_stops:
        try:
            batch = client.get_stop_departures(
                stop.stop_id,
                limit=departure_limit,
            )
            api_calls_succeeded += 1
            observations_generated += len(batch.delay_observations)

            save_summary = repository.save_search_collection_batch(batch)
            observations_saved += save_summary.delay_observations_saved
            duplicate_observations_skipped += (
                save_summary.duplicate_observations_skipped
            )
        except Exception as exc:
            api_calls_failed += 1
            error = CollectionError(
                stop_id=stop.stop_id,
                stop_name=stop.stop_name,
                message=str(exc),
            )
            errors.append(error)

    return CollectionSummary(
        stops_requested=len(monitored_stops),
        api_calls_succeeded=api_calls_succeeded,
        api_calls_failed=api_calls_failed,
        observations_generated=observations_generated,
        observations_saved=observations_saved,
        duplicate_observations_skipped=duplicate_observations_skipped,
        errors=tuple(errors),
    )


def main() -> None:
    summary = run_collection()
    print(json.dumps(summary.to_dict(), default=str, indent=2))


if __name__ == "__main__":
    main()
