"""Client and response adapters for the BKK FUTAR API."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from bkk_delays.config import AppConfig
from bkk_delays.delay_processor import (
    categorize_delay,
    count_delay_seconds,
    create_observation_id,
)
from bkk_delays.models import (
    CollectionRun,
    DelayObservation,
    Route,
    SearchCollectionBatch,
    StationSearchResult,
    Stop,
)

LOGGER = logging.getLogger(__name__)
try:
    BUDAPEST_TZ = ZoneInfo("Europe/Budapest")
except ZoneInfoNotFoundError:
    BUDAPEST_TZ = datetime.now().astimezone().tzinfo or timezone.utc


class BkkApiError(RuntimeError):
    """Raised when the BKK API cannot return a usable response."""


class BkkApiClient:
    def __init__(
        self,
        config: AppConfig,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.session.trust_env = False

    def search_stations(self, query: str, limit: int = 11) -> list[StationSearchResult]:
        cleaned_query = query.strip()
        if len(cleaned_query) < 4:
            return []

        payload = self._get(
            "search",
            {
                "query": cleaned_query,
                "minResult": str(limit),
                "includeReferences": "stops,routes",
            },
        )
        if payload.get("status") != "OK":
            status = payload.get("status", "UNKNOWN")
            text = payload.get("text", "")
            LOGGER.warning(
                "BKK search returned non-OK status %s: %s",
                status,
                _format_payload(payload),
            )
            raise BkkApiError(f"BKK search failed with status {status}: {text}")

        return parse_station_search_results(payload, limit=limit)

    def get_stop_departures(
        self,
        stop_id: str,
        limit: int = 10,
    ) -> SearchCollectionBatch:
        cleaned_stop_id = stop_id.strip()
        if not cleaned_stop_id:
            return _empty_search_collection_batch()

        payload = self._get(
            "arrivals-and-departures-for-stop",
            {
                "stopId": cleaned_stop_id,
                "onlyDepartures": "true",
                "stopTimeType": "DEPARTURE",
                "limit": str(limit),
                "includeReferences": "stops,routes,trips",
            },
        )
        if payload.get("status") != "OK":
            status = payload.get("status", "UNKNOWN")
            text = payload.get("text", "")
            LOGGER.warning(
                "BKK stop departures returned non-OK status %s: %s",
                status,
                _format_payload(payload),
            )
            raise BkkApiError(f"BKK stop departures failed with status {status}: {text}")

        return parse_stop_departures(payload, stop_id=cleaned_stop_id, limit=limit)

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        if not self.config.bkk_api_key:
            raise BkkApiError("BKK_API_KEY is not configured.")

        url = (
            f"{self.config.bkk_api_base_url.rstrip('/')}/"
            f"{self.config.bkk_api_dialect}/api/where/{endpoint}"
        )
        request_params = {
            "version": self.config.bkk_api_version,
            "key": self.config.bkk_api_key,
            **params,
        }

        try:
            response = self.session.get(
                url,
                params=request_params,
                timeout=self.config.bkk_api_timeout_seconds,
            )
            LOGGER.info("BKK API GET %s returned HTTP %s", endpoint, response.status_code)
            response.raise_for_status()
        except requests.HTTPError as exc:
            error_response = exc.response
            response_text = error_response.text if error_response is not None else ""
            LOGGER.warning(
                "BKK API %s HTTP error response: %s",
                endpoint,
                response_text,
            )
            raise BkkApiError(f"BKK API request failed: {exc}") from exc
        except requests.RequestException as exc:
            raise BkkApiError(f"BKK API request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            LOGGER.warning(
                "BKK API %s returned invalid JSON: %s",
                endpoint,
                response.text,
            )
            raise BkkApiError("BKK API returned invalid JSON.") from exc

        LOGGER.info("BKK API %s response: %s", endpoint, _format_payload(payload))
        return payload


def _format_payload(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)


def parse_station_search_results(
    payload: dict[str, Any],
    limit: int = 8,
) -> list[StationSearchResult]:
    data = _as_dict(payload.get("data"))
    entry = _as_dict(data.get("entry"))
    references = _as_dict(data.get("references"))

    stop_references = _stop_reference_map(references.get("stops"))
    route_references = _stop_reference_map(references.get("routes"))
    stop_ids = _string_items(entry.get("stopIds"))
    if not stop_ids:
        stop_ids = list(stop_references)

    results: list[StationSearchResult] = []
    seen: set[str] = set()
    for stop_id in stop_ids:
        if stop_id in seen:
            continue
        raw_stop = stop_references.get(stop_id)
        if not raw_stop:
            continue
        station = _station_from_reference(stop_id, raw_stop, route_references)
        if station is None:
            continue
        results.append(station)
        seen.add(stop_id)
        if len(results) >= limit:
            break

    return results


def parse_stop_departures(
    payload: dict[str, Any],
    stop_id: str,
    limit: int = 10,
) -> SearchCollectionBatch:
    started_at = datetime.now(timezone.utc)
    data = _as_dict(payload.get("data"))
    entry = _as_dict(data.get("entry"))
    references = _as_dict(data.get("references"))

    stop_references = _stop_reference_map(references.get("stops"))
    route_references = _stop_reference_map(references.get("routes"))
    trip_references = _stop_reference_map(references.get("trips"))

    collection_run_id = str(uuid.uuid4())
    routes: dict[str, Route] = {}
    stops: dict[str, Stop] = {}
    observations: list[DelayObservation] = []

    for raw_stop_time in _dict_items(entry.get("stopTimes")):
        observation = _observation_from_stop_time(
            raw_stop_time,
            fallback_stop_id=stop_id,
            collection_run_id=collection_run_id,
            observation_index=len(observations),
            stop_references=stop_references,
            route_references=route_references,
            trip_references=trip_references,
        )
        if observation is None:
            continue

        route, stop, delay_observation = observation
        routes.setdefault(route.id, route)
        stops.setdefault(stop.id, stop)
        observations.append(delay_observation)
        if len(observations) >= limit:
            break

    finished_at = datetime.now(timezone.utc)
    return SearchCollectionBatch(
        routes=tuple(routes.values()),
        stops=tuple(stops.values()),
        collection_run=CollectionRun(
            id=collection_run_id,
            started_at=started_at,
            finished_at=finished_at,
            status="success",
            records_saved=len(observations),
        ),
        delay_observations=tuple(observations),
    )


def _observation_from_stop_time(
    stop_time: dict[str, Any],
    fallback_stop_id: str,
    collection_run_id: str,
    observation_index: int,
    stop_references: dict[str, dict[str, Any]],
    route_references: dict[str, dict[str, Any]],
    trip_references: dict[str, dict[str, Any]],
) -> Optional[tuple[Route, Stop, DelayObservation]]:
    expected_timestamp = _optional_int(stop_time.get("departureTime"))
    if expected_timestamp is None:
        return None

    realtime_timestamp = _optional_int(stop_time.get("predictedDepartureTime"))
    stop_id = str(stop_time.get("stopId") or fallback_stop_id)
    stop_reference = stop_references.get(stop_id, {})
    stop_name = str(stop_reference.get("name") or stop_id)
    stop_sequence = _optional_int(stop_time.get("stopSequence")) or 0

    trip_id = str(stop_time.get("tripId") or "")
    trip_reference = trip_references.get(trip_id, {})
    route_id = str(stop_time.get("routeId") or trip_reference.get("routeId") or "")
    route_reference = route_references.get(route_id, {})
    route_short_name = str(
        stop_time.get("routeShortName")
        or route_reference.get("shortName")
        or route_id
        or "-"
    )
    route_id = route_id or route_short_name
    route_type = str(route_reference.get("type") or "")
    destination_name = str(
        stop_time.get("stopHeadsign")
        or trip_reference.get("tripHeadsign")
        or trip_reference.get("headsign")
        or "-"
    )

    scheduled_departure = _datetime_from_epoch_seconds(expected_timestamp)
    predicted_departure = (
        _datetime_from_epoch_seconds(realtime_timestamp)
        if realtime_timestamp is not None
        else scheduled_departure
    )
    delay_seconds = count_delay_seconds(scheduled_departure, predicted_departure)
    created_at = datetime.now(timezone.utc)

    created_at = datetime.now(timezone.utc)

    return (
        Route(
            id=route_id,
            short_name=route_short_name,
            route_type=route_type,
        ),
        Stop(
            id=stop_id,
            name=stop_name,
            lat=_optional_float(stop_reference.get("lat")),
            lon=_optional_float(stop_reference.get("lon")),
        ),
        DelayObservation(
            id=create_observation_id(
                collection_run_id,
                trip_id,
                stop_id,
                scheduled_departure,
                observation_index,
                collected_at=created_at,
            ),
            collection_run_id=collection_run_id,
            route_id=route_id,
            stop_id=stop_id,
            trip_id=trip_id,
            headsign=destination_name,
            direction_id=str(trip_reference.get("directionId") or ""),
            stop_sequence=stop_sequence,
            scheduled_departure=scheduled_departure,
            predicted_departure=predicted_departure,
            delay_seconds=delay_seconds,
            delay_category=categorize_delay(delay_seconds),
            created_at=created_at,
        ),
    )


def _empty_search_collection_batch() -> SearchCollectionBatch:
    now = datetime.now(timezone.utc)
    return SearchCollectionBatch(
        routes=(),
        stops=(),
        collection_run=CollectionRun(
            id=str(uuid.uuid4()),
            started_at=now,
            finished_at=now,
            status="empty",
            records_saved=0,
        ),
        delay_observations=(),
    )


def _stop_reference_map(raw_stops: Any) -> dict[str, dict[str, Any]]:
    if isinstance(raw_stops, dict):
        return {
            str(stop_id): stop
            for stop_id, stop in raw_stops.items()
            if isinstance(stop, dict)
        }

    if isinstance(raw_stops, list):
        stops: dict[str, dict[str, Any]] = {}
        for stop in raw_stops:
            if not isinstance(stop, dict):
                continue
            stop_id = stop.get("id")
            if stop_id:
                stops[str(stop_id)] = stop
        return stops

    return {}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _station_from_reference(
    fallback_stop_id: str,
    raw_stop: dict[str, Any],
    route_references: dict[str, dict[str, Any]],
) -> Optional[StationSearchResult]:
    stop_id = str(raw_stop.get("id") or fallback_stop_id)
    name = str(raw_stop.get("name") or "").strip()
    route_ids = _string_items(raw_stop.get("routeIds"))
    route_numbers = ""
    for route_id in route_ids:
        route_info = route_references.get(route_id)
        if route_info:
            route_short_name = str(route_info.get("shortName") or "").strip()
            if route_short_name:
                route_numbers += route_short_name + ", "
    if not stop_id or not name:
        return None

    return StationSearchResult(
        stop_id=stop_id,
        name=name,
        code=str(raw_stop.get("code") or ""),
        direction=str(raw_stop.get("direction") or ""),
        lat=_optional_float(raw_stop.get("lat")),
        lon=_optional_float(raw_stop.get("lon")),
        route_ids=tuple(_string_items(raw_stop.get("routeIds"))),
        route_number=route_numbers.rstrip(", "),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [str(item) for item in value if item]


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_from_epoch_seconds(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=BUDAPEST_TZ)
