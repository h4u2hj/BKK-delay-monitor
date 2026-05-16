from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, jsonify, render_template, request

from bkk_delays.bkk_api import BkkApiClient, BkkApiError
from bkk_delays.config import AppConfig, load_config
from bkk_delays.firestore_repository import (
    FirestoreRepository,
    FirestoreRepositoryError,
)
from bkk_delays.models import DelayObservation, Route, Stop


def create_app(
    config: Optional[AppConfig] = None,
    bkk_client: Optional[BkkApiClient] = None,
    firestore_repository: Optional[FirestoreRepository] = None,
) -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("bkk_delays").setLevel(logging.INFO)

    app = Flask(__name__)
    app_config = config or load_config()
    app.config["APP_CONFIG"] = app_config
    app.config["BKK_CLIENT"] = bkk_client or BkkApiClient(app_config)
    app.config["FIRESTORE_REPOSITORY"] = (
        firestore_repository or FirestoreRepository(app_config)
    )
    app.config["LAST_SEARCH_COLLECTION_BATCH"] = None

    @app.context_processor
    def inject_firebase_config():
        return {"firebase_config": app_config.firebase_web_config}

    @app.get("/")
    def index():
        station_id = request.args.get("station_id", "").strip()
        station_name = request.args.get("station", "").strip()
        departures = []
        departure_error = ""
        persistence_error = ""

        if station_id:
            try:
                batch = app.config["BKK_CLIENT"].get_stop_departures(
                    station_id,
                    limit=8,
                )
                app.config["LAST_SEARCH_COLLECTION_BATCH"] = batch
                route_by_id = {route.id: route for route in batch.routes}
                stop_by_id = {stop.id: stop for stop in batch.stops}
                departures = [
                    _departure_view_model(
                        observation,
                        route_by_id,
                        stop_by_id,
                    )
                    for observation in batch.delay_observations
                ]
                try:
                    repository = app.config["FIRESTORE_REPOSITORY"]
                    repository.save_search_collection_batch(batch)
                except FirestoreRepositoryError as exc:
                    logging.getLogger(__name__).warning(
                        "Firestore persistence failed: %s",
                        exc,
                    )
                    persistence_error = str(exc)
            except BkkApiError as exc:
                departure_error = str(exc)

        return render_template(
            "index.html",
            active_page="search",
            selected_station_id=station_id,
            selected_station_name=station_name,
            departures=departures,
            departure_error=departure_error,
            persistence_error=persistence_error,
        )

    @app.get("/api/stations")
    def station_search():
        query = request.args.get("q", "").strip()
        if len(query) < 4:
            return jsonify({"stations": []})

        try:
            stations = app.config["BKK_CLIENT"].search_stations(query)
        except BkkApiError as exc:
            return jsonify({"error": str(exc), "stations": []}), 502

        return jsonify({"stations": [station.to_dict() for station in stations]})

    @app.get("/history")
    def history():
        observations = []
        history_error = ""
        try:
            repository = app.config["FIRESTORE_REPOSITORY"]
            observations = repository.list_recent_history_entries(limit=50)
        except FirestoreRepositoryError as exc:
            logging.getLogger(__name__).warning(
                "Firestore history read failed: %s",
                exc,
            )
            history_error = str(exc)

        return render_template(
            "history.html",
            active_page="history",
            observations=observations,
            history_error=history_error,
        )

    return app


def _departure_view_model(
    observation: DelayObservation,
    route_by_id: dict[str, Route],
    stop_by_id: dict[str, Stop],
) -> dict[str, str]:
    stop = stop_by_id[observation.stop_id]
    route = route_by_id[observation.route_id]
    return {
        "stop_name": stop.name,
        "route_short_name": route.short_name,
        "destination_name": observation.headsign,
        "expected_departure": observation.scheduled_departure.strftime("%H:%M"),
        "realtime_departure": observation.predicted_departure.strftime("%H:%M"),
        "delay_seconds": str(observation.delay_seconds),
    }
