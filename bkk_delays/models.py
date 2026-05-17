"""Typed domain models used by the BKK delay monitor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class MonitoredStop:
    stop_id: str
    stop_name: str
    route_short_names: tuple[str, ...]
    direction_label: str
    stop_sequence: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass(frozen=True)
class Route:
    id: str
    short_name: str
    route_type: str


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lat: Optional[float]
    lon: Optional[float]


@dataclass(frozen=True)
class CollectionRun:
    id: str
    started_at: datetime
    finished_at: Optional[datetime]
    status: str
    records_saved: int
    error_message: str = ""


@dataclass(frozen=True)
class DelayObservation:
    id: str
    collection_run_id: str
    route_id: str
    stop_id: str
    trip_id: str
    headsign: str
    direction_id: str
    stop_sequence: int
    scheduled_departure: datetime
    predicted_departure: datetime
    delay_seconds: int
    delay_category: str
    created_at: datetime


@dataclass(frozen=True)
class SearchCollectionBatch:
    routes: tuple[Route, ...]
    stops: tuple[Stop, ...]
    collection_run: CollectionRun
    delay_observations: tuple[DelayObservation, ...]


@dataclass(frozen=True)
class ApiCallLog:
    endpoint: str
    success: bool
    started_at: datetime
    duration_ms: int
    status_code: Optional[int] = None
    response_status: str = ""
    response_text: str = ""
    error: str = ""
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StationSearchResult:
    stop_id: str
    name: str
    code: str = ""
    direction: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    route_number: Optional[str] = None
    route_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.stop_id,
            "name": self.name,
            "code": self.code,
            "direction": self.direction,
            "lat": self.lat,
            "lon": self.lon,
            "route_ids": list(self.route_ids),
            "route_number": self.route_number,
        }


MONITORED_STOPS: tuple[MonitoredStop, ...] = (
    MonitoredStop("BKK_F00199", "Mechwart liget", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F00198", "Mechwart liget", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F00192", "Margit hid, budai hidfo H", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F00189", "Margit hid, budai hidfo H", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F00926", "Jaszai Mari ter", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F00925", "Jaszai Mari ter", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F00935", "Nyugati palyaudvar M", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F00933", "Nyugati palyaudvar M", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F01037", "Kiraly utca / Erzsebet korut", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F01035", "Kiraly utca / Erzsebet korut", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F01169", "Blaha Lujza ter M", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F01168", "Blaha Lujza ter M", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F01199", "Harminckettesek tere ", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F01197", "Harminckettesek tere ", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F01194", "Corvin-negyed M", ("4", "6"), "Ujbuda / Moricz direction"),
    MonitoredStop("BKK_F01191", "Corvin-negyed M", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F02225", "Petofi hid, budai hidfo", ("4", "6"), "Szell Kalman direction"),
    MonitoredStop("BKK_F02224", "Petofi hid, budai hidfo", ("4", "6"), "Ujbuda / Moricz direction"),
)
