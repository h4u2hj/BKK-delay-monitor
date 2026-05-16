from datetime import datetime, timedelta, timezone

from bkk_delays import bkk_api
from bkk_delays.bkk_api import parse_station_search_results, parse_stop_departures


def test_parse_station_search_results_from_mobile_references():
    payload = {
        "status": "OK",
        "data": {
            "entry": {"stopIds": ["BKK_STOP_1"]},
            "references": {
                "stops": [
                    {
                        "id": "BKK_STOP_1",
                        "name": "Oktogon M",
                        "code": "123456",
                        "direction": "Szell Kalman ter",
                        "lat": 47.505,
                        "lon": 19.063,
                        "routeIds": ["BKK_3040", "BKK_3060"],
                    }
                ]
            },
        },
    }

    stations = parse_station_search_results(payload)

    assert len(stations) == 1
    assert stations[0].stop_id == "BKK_STOP_1"
    assert stations[0].name == "Oktogon M"
    assert stations[0].route_ids == ("BKK_3040", "BKK_3060")


def test_parse_station_search_results_from_otp_references():
    payload = {
        "status": "OK",
        "data": {
            "entry": {"stopIds": ["BKK_STOP_2"]},
            "references": {
                "stops": {
                    "BKK_STOP_2": {
                        "id": "BKK_STOP_2",
                        "name": "Blaha Lujza ter M",
                    }
                }
            },
        },
    }

    stations = parse_station_search_results(payload)

    assert len(stations) == 1
    assert stations[0].stop_id == "BKK_STOP_2"
    assert stations[0].name == "Blaha Lujza ter M"


def test_parse_stop_departures_uses_references_and_converts_epoch_seconds(monkeypatch):
    budapest_timezone = timezone(timedelta(hours=2))
    monkeypatch.setattr(bkk_api, "BUDAPEST_TZ", budapest_timezone)
    expected = datetime(2026, 5, 16, 14, 5, tzinfo=budapest_timezone)
    realtime = datetime(2026, 5, 16, 14, 7, tzinfo=budapest_timezone)
    payload = {
        "status": "OK",
        "data": {
            "entry": {
                "stopTimes": [
                    {
                        "stopId": "BKK_STOP_1",
                        "departureTime": int(expected.timestamp()),
                        "predictedDepartureTime": int(realtime.timestamp()),
                        "stopHeadsign": "Ujbuda-kozpont M",
                        "tripId": "BKK_TRIP_1",
                    }
                ]
            },
            "references": {
                "stops": {
                    "BKK_STOP_1": {
                        "id": "BKK_STOP_1",
                        "name": "Oktogon M",
                        "lat": 47.505,
                        "lon": 19.063,
                    }
                },
                "trips": {
                    "BKK_TRIP_1": {
                        "id": "BKK_TRIP_1",
                        "routeId": "BKK_ROUTE_4",
                        "directionId": "1",
                    }
                },
                "routes": {
                    "BKK_ROUTE_4": {
                        "id": "BKK_ROUTE_4",
                        "shortName": "4",
                        "type": "TRAM",
                    }
                },
            },
        },
    }
    payload["data"]["entry"]["stopTimes"][0]["stopSequence"] = 12

    batch = parse_stop_departures(payload, stop_id="BKK_STOP_1", limit=5)

    assert batch.collection_run.status == "success"
    assert batch.collection_run.records_saved == 1
    assert len(batch.routes) == 1
    assert batch.routes[0].id == "BKK_ROUTE_4"
    assert batch.routes[0].short_name == "4"
    assert batch.routes[0].route_type == "TRAM"
    assert len(batch.stops) == 1
    assert batch.stops[0].id == "BKK_STOP_1"
    assert batch.stops[0].name == "Oktogon M"
    assert batch.stops[0].lat == 47.505
    assert batch.stops[0].lon == 19.063
    assert len(batch.delay_observations) == 1
    observation = batch.delay_observations[0]
    assert observation.collection_run_id == batch.collection_run.id
    assert observation.route_id == "BKK_ROUTE_4"
    assert observation.stop_id == "BKK_STOP_1"
    assert observation.trip_id == "BKK_TRIP_1"
    assert observation.headsign == "Ujbuda-kozpont M"
    assert observation.direction_id == "1"
    assert observation.stop_sequence == 12
    assert observation.scheduled_departure == expected
    assert observation.predicted_departure == realtime
    assert observation.delay_seconds == 120
    assert observation.delay_category == "minor_delay"
