"""PostgreSQL persistence for normalized BKK delay entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql

from bkk_delays.config import AppConfig
from bkk_delays.delay_processor import create_observation_duplicate_key
from bkk_delays.models import SearchCollectionBatch

DISPLAY_TIMEZONE = ZoneInfo("Europe/Budapest")


class PostgreSQLRepositoryError(RuntimeError):
    """Raised when PostgreSQL persistence is enabled but cannot complete."""


@dataclass(frozen=True)
class PostgreSQLSaveSummary:
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
class PostgreSQLHistoryEntry:
    station_name: str
    route_short_name: str
    destination_name: str
    expected_departure: str
    realtime_departure: str
    delay_seconds: str


class PostgreSQLRepository:
    """Save database-ready entity batches to PostgreSQL tables."""

    def __init__(
        self,
        config: AppConfig,
        connection_factory: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._connection_factory = connection_factory or self._connect

    def save_search_collection_batch(
        self,
        batch: SearchCollectionBatch,
    ) -> PostgreSQLSaveSummary:
        """Upload every normalized entity in a search collection batch."""

        if not self.config.use_postgres:
            return PostgreSQLSaveSummary(enabled=False)

        try:
            with self._connection_factory() as connection:
                _set_search_path(connection, self.config.postgres_schema)
                return _save_search_collection_batch(connection, batch)
        except Exception as exc:
            raise PostgreSQLRepositoryError(
                f"PostgreSQL batch upload failed: {exc}"
            ) from exc

    def list_recent_history_entries(
        self,
        limit: int = 50,
    ) -> list[PostgreSQLHistoryEntry]:
        """Read recent observations from PostgreSQL and join route/stop rows."""

        if not self.config.use_postgres:
            return []

        try:
            with self._connection_factory() as connection:
                _set_search_path(connection, self.config.postgres_schema)
                return _read_history_entries(connection, limit=limit)
        except Exception as exc:
            raise PostgreSQLRepositoryError(
                f"PostgreSQL history read failed: {exc}"
            ) from exc

    def _connect(self) -> psycopg.Connection:
        missing = _missing_postgres_settings(self.config)
        if missing:
            raise PostgreSQLRepositoryError(
                "PostgreSQL is enabled but missing environment settings: "
                + ", ".join(missing)
            )

        return psycopg.connect(
            host=self.config.postgres_host,
            port=self.config.postgres_port,
            dbname=self.config.postgres_db,
            user=self.config.postgres_user,
            password=self.config.postgres_password,
            sslmode=self.config.postgres_sslmode,
            connect_timeout=self.config.postgres_connect_timeout_seconds,
        )


def _missing_postgres_settings(config: AppConfig) -> list[str]:
    required = {
        "POSTGRES_HOST": config.postgres_host,
        "POSTGRES_DB": config.postgres_db,
        "POSTGRES_USER": config.postgres_user,
        "POSTGRES_PASSWORD": config.postgres_password,
        "POSTGRES_SCHEMA": config.postgres_schema,
    }
    return [name for name, value in required.items() if not str(value).strip()]


def _set_search_path(connection: Any, schema_name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SET search_path TO {}, public").format(
                sql.Identifier(schema_name)
            )
        )


def _save_search_collection_batch(
    connection: Any,
    batch: SearchCollectionBatch,
) -> PostgreSQLSaveSummary:
    with connection.cursor() as cursor:
        for route in batch.routes:
            cursor.execute(
                """
                INSERT INTO routes (id, short_name, route_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    short_name = EXCLUDED.short_name,
                    route_type = EXCLUDED.route_type
                """,
                (route.id, route.short_name, route.route_type),
            )

        for stop in batch.stops:
            cursor.execute(
                """
                INSERT INTO stops (id, name, lat, lon)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    lat = EXCLUDED.lat,
                    lon = EXCLUDED.lon
                """,
                (stop.id, stop.name, stop.lat, stop.lon),
            )

        cursor.execute(
            """
            INSERT INTO collection_runs (
                id,
                started_at,
                finished_at,
                status,
                records_saved,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                started_at = EXCLUDED.started_at,
                finished_at = EXCLUDED.finished_at,
                status = EXCLUDED.status,
                records_saved = EXCLUDED.records_saved,
                error_message = EXCLUDED.error_message
            """,
            (
                batch.collection_run.id,
                batch.collection_run.started_at,
                batch.collection_run.finished_at,
                batch.collection_run.status,
                0,
                batch.collection_run.error_message,
            ),
        )

        inserted_observations = 0
        for observation in batch.delay_observations:
            cursor.execute(
                """
                INSERT INTO delay_observations (
                    id,
                    collection_run_id,
                    route_id,
                    stop_id,
                    trip_id,
                    headsign,
                    direction_id,
                    stop_sequence,
                    scheduled_departure,
                    predicted_departure,
                    delay_seconds,
                    delay_category,
                    created_at,
                    duplicate_key
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (duplicate_key) DO NOTHING
                RETURNING id
                """,
                (
                    observation.id,
                    observation.collection_run_id,
                    observation.route_id,
                    observation.stop_id,
                    observation.trip_id,
                    observation.headsign,
                    observation.direction_id,
                    observation.stop_sequence,
                    observation.scheduled_departure,
                    observation.predicted_departure,
                    observation.delay_seconds,
                    observation.delay_category,
                    observation.created_at,
                    create_observation_duplicate_key(
                        observation.trip_id,
                        observation.stop_id,
                        observation.scheduled_departure,
                    ),
                ),
            )
            if cursor.fetchone() is not None:
                inserted_observations += 1

        cursor.execute(
            """
            UPDATE collection_runs
            SET records_saved = %s
            WHERE id = %s
            """,
            (inserted_observations, batch.collection_run.id),
        )

    duplicate_observations_skipped = (
        len(batch.delay_observations) - inserted_observations
    )
    return PostgreSQLSaveSummary(
        enabled=True,
        routes_saved=len(batch.routes),
        stops_saved=len(batch.stops),
        collection_runs_saved=1,
        delay_observations_saved=inserted_observations,
        duplicate_observations_skipped=duplicate_observations_skipped,
    )


def _read_history_entries(
    connection: Any,
    limit: int,
) -> list[PostgreSQLHistoryEntry]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                stop.name AS station_name,
                route.short_name AS route_short_name,
                observation.headsign AS destination_name,
                observation.scheduled_departure,
                observation.predicted_departure,
                observation.delay_seconds
            FROM delay_observations AS observation
            JOIN stops AS stop ON stop.id = observation.stop_id
            JOIN routes AS route ON route.id = observation.route_id
            ORDER BY observation.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [_history_entry_from_row(row) for row in cursor.fetchall()]


def _history_entry_from_row(row: tuple[Any, ...]) -> PostgreSQLHistoryEntry:
    return PostgreSQLHistoryEntry(
        station_name=str(row[0] or "-"),
        route_short_name=str(row[1] or "-"),
        destination_name=str(row[2] or "-"),
        expected_departure=_format_history_time(row[3]),
        realtime_departure=_format_history_time(row[4]),
        delay_seconds=str(row[5] or 0),
    )


def _format_history_time(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(DISPLAY_TIMEZONE).strftime("%H:%M")
    return "-"
