"""BigQuery analytics reads for normalized BKK delay entities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from bkk_delays.config import AppConfig
from bkk_delays.models import DelayObservation, Stop

ANALYTICS_QUERY_FILE = (
    Path(__file__).resolve().parent.parent / "sql" / "bigquery_analytics_queries.sql"
)
QUERY_NAME_PATTERN = re.compile(r"^--\s*name:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
ROUTES_TABLE = "routes"
STOPS_TABLE = "stops"
DELAY_OBSERVATIONS_TABLE = "delay_observations"
DELAY_PREDICTION_MODEL = "delay_predictor_by_station_time"

_BQ_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GCP_PROJECT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9]$")
TRAM_4_6_ROUTE_IDS = {"3040", "3060"}
MORICZ_UJBUDA_HEADSIGN = "Újbuda-központ M / Móricz Zsigmond körtér M"
_MORICZ_UJBUDA_HEADSIGNS = {
    "ujbuda-kozpont m",
    "újbuda-központ m",
    "moricz zsigmond korter m",
    "móricz zsigmond körtér m",
}


class BigQueryRepositoryError(RuntimeError):
    """Raised when BigQuery analytics cannot complete."""


@dataclass(frozen=True)
class AverageDelayByStop:
    stop_id: str
    stop_name: str
    headsign: str
    observation_count: int
    average_delay_seconds: float


@dataclass(frozen=True)
class DelayedRatioByPeriod:
    period_start: datetime
    observation_count: int
    delayed_count: int
    delayed_ratio: float
    average_delay_seconds: float = 0.0


@dataclass(frozen=True)
class ProblematicStop:
    stop_id: str
    stop_name: str
    headsign: str
    observation_count: int
    average_delay_seconds: float
    delayed_ratio: float
    major_delay_count: int


@dataclass(frozen=True)
class PredictedDelayByStation:
    stop_id: str
    stop_name: str
    headsign: str
    prediction_time: datetime
    predicted_delay_seconds: float


@dataclass(frozen=True)
class BigQueryStatistics:
    average_delay_by_stop: tuple[AverageDelayByStop, ...]
    delayed_ratio_by_period: tuple[DelayedRatioByPeriod, ...]
    most_problematic_stops: tuple[ProblematicStop, ...]
    predicted_delay_by_station: tuple[PredictedDelayByStation, ...] = ()


T = TypeVar("T")


class BigQueryRepository:
    """Read analytics from BigQuery normalized delay tables."""

    def __init__(
        self,
        config: AppConfig,
        client: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._client = client
        self._init_error = ""
        self._queries = load_named_sql_queries()

        if self.config.use_bigquery and self._client is None:
            try:
                self._client = _build_bigquery_client(config)
            except Exception as exc:
                self._init_error = _format_bigquery_init_error(exc)

    def load_statistics(self) -> BigQueryStatistics:
        """Read all statistics needed by the Flask statistics page."""

        if not self.config.use_bigquery:
            return empty_statistics()

        return BigQueryStatistics(
            average_delay_by_stop=tuple(self.average_delay_by_stop()),
            delayed_ratio_by_period=tuple(self.delayed_ratio_by_time_period()),
            most_problematic_stops=tuple(self.most_problematic_stops()),
            predicted_delay_by_station=tuple(self.predicted_delay_by_station()),
        )

    def average_delay_by_stop(self) -> list[AverageDelayByStop]:
        return self._query_rows(
            self._render_query("average_delay_by_stop"),
            _average_delay_by_stop_from_row,
        )

    def delayed_ratio_by_time_period(
        self,
        hours_back: int = 24,
    ) -> list[DelayedRatioByPeriod]:
        return self._query_rows(
            self._render_query("delayed_ratio_by_time_period"),
            _delayed_ratio_by_period_from_row,
            [scalar_query_parameter("hours", "INT64", hours_back)],
        )

    def most_problematic_stops(self) -> list[ProblematicStop]:
        return self._query_rows(
            self._render_query("most_problematic_stops"),
            _problematic_stop_from_row,
        )

    def predicted_delay_by_station(self) -> list[PredictedDelayByStation]:
        return self._query_rows(
            self._render_query("predicted_delay_by_station"),
            _predicted_delay_by_station_from_row,
        )

    def _query_rows(
        self,
        sql: str,
        mapper: Callable[[Any], T],
        query_parameters: Optional[Sequence[Any]] = None,
    ) -> list[T]:
        client = self._require_client()
        job_config = None
        if bigquery is not None and query_parameters:
            job_config = bigquery.QueryJobConfig(
                query_parameters=list(query_parameters)
            )

        try:
            rows = client.query(sql, job_config=job_config).result()
            return [mapper(row) for row in rows]
        except Exception as exc:
            raise BigQueryRepositoryError(
                f"BigQuery analytics query failed: {exc}"
            ) from exc

    def _table_id(self, table_name: str) -> str:
        dataset_name = _validate_bigquery_identifier(
            self.config.bigquery_dataset,
            "BIGQUERY_DATASET",
        )
        table_name = _validate_bigquery_identifier(table_name, "BigQuery table name")
        project_id = _project_id(self.config, self._client)
        return f"{project_id}.{dataset_name}.{table_name}"

    def _render_query(self, query_name: str) -> str:
        try:
            query_template = self._queries[query_name]
        except KeyError as exc:
            raise BigQueryRepositoryError(
                f"BigQuery SQL query is missing from {ANALYTICS_QUERY_FILE}: "
                f"{query_name}"
            ) from exc

        return query_template.format(
            delay_observations_table=self._table_id(DELAY_OBSERVATIONS_TABLE),
            stops_table=self._table_id(STOPS_TABLE),
            routes_table=self._table_id(ROUTES_TABLE),
            delay_prediction_model=self._table_id(DELAY_PREDICTION_MODEL),
        )

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client

        message = self._init_error or "BigQuery client is not configured."
        raise BigQueryRepositoryError(message)


def statistics_from_observations(
    observations: Sequence[DelayObservation],
    stops: Sequence[Stop] = (),
) -> BigQueryStatistics:
    """Build sample-mode statistics from in-memory normalized observations."""

    stop_names = {stop.id: stop.name for stop in stops}
    observations = [
        observation
        for observation in observations
        if _is_tram_4_6_observation(observation)
    ]
    if not observations:
        return empty_statistics()

    return BigQueryStatistics(
        average_delay_by_stop=tuple(
            AverageDelayByStop(
                stop_id=stop_key[0],
                stop_name=stop_names.get(stop_key[0], stop_key[0]),
                headsign=stop_key[1],
                observation_count=len(stop_observations),
                average_delay_seconds=_average_delay(stop_observations),
            )
            for stop_key, stop_observations in _group_by(
                observations,
                lambda observation: (
                    observation.stop_id,
                    _normalized_headsign(observation.headsign),
                ),
            )
        ),
        delayed_ratio_by_period=tuple(
            DelayedRatioByPeriod(
                period_start=period,
                observation_count=len(period_observations),
                delayed_count=sum(
                    1
                    for observation in period_observations
                    if observation.delay_seconds > 60
                ),
                delayed_ratio=_delayed_ratio(period_observations),
                average_delay_seconds=_average_delay(period_observations),
            )
            for period, period_observations in _group_by(
                observations,
                lambda observation: _truncate_hour(
                    observation.scheduled_departure
                ),
            )
        ),
        most_problematic_stops=tuple(
            ProblematicStop(
                stop_id=stop_key[0],
                stop_name=stop_names.get(stop_key[0], stop_key[0]),
                headsign=stop_key[1],
                observation_count=len(stop_observations),
                average_delay_seconds=_average_delay(stop_observations),
                delayed_ratio=_delayed_ratio(stop_observations),
                major_delay_count=sum(
                    1
                    for observation in stop_observations
                    if observation.delay_category == "major_delay"
                ),
            )
            for stop_key, stop_observations in _group_by(
                observations,
                lambda observation: (
                    observation.stop_id,
                    _normalized_headsign(observation.headsign),
                ),
            )
        ),
        predicted_delay_by_station=(),
    )


def load_named_sql_queries(
    query_file: Path = ANALYTICS_QUERY_FILE,
) -> dict[str, str]:
    """Load named BigQuery SQL blocks from the analytics query file."""

    if not query_file.is_file():
        raise BigQueryRepositoryError(f"BigQuery SQL file is missing: {query_file}")

    queries: dict[str, list[str]] = {}
    current_name = ""

    for line in query_file.read_text(encoding="utf-8").splitlines():
        match = QUERY_NAME_PATTERN.match(line)
        if match:
            current_name = match.group(1)
            queries[current_name] = []
            continue

        if current_name:
            queries[current_name].append(line)

    return {
        name: _strip_trailing_semicolon("\n".join(lines).strip())
        for name, lines in queries.items()
    }


def empty_statistics() -> BigQueryStatistics:
    return BigQueryStatistics(
        average_delay_by_stop=(),
        delayed_ratio_by_period=(),
        most_problematic_stops=(),
        predicted_delay_by_station=(),
    )


def _strip_trailing_semicolon(sql: str) -> str:
    return sql[:-1].rstrip() if sql.endswith(";") else sql


def scalar_query_parameter(name: str, parameter_type: str, value: Any) -> Any:
    if bigquery is None:
        return (name, parameter_type, value)
    return bigquery.ScalarQueryParameter(name, parameter_type, value)


def _average_delay_by_stop_from_row(row: Any) -> AverageDelayByStop:
    return AverageDelayByStop(
        stop_id=str(_row_value(row, "stop_id") or ""),
        stop_name=str(_row_value(row, "stop_name") or ""),
        headsign=str(_row_value(row, "headsign") or "unknown"),
        observation_count=int(_row_value(row, "observation_count") or 0),
        average_delay_seconds=float(_row_value(row, "average_delay_seconds") or 0),
    )


def _delayed_ratio_by_period_from_row(row: Any) -> DelayedRatioByPeriod:
    return DelayedRatioByPeriod(
        period_start=_as_datetime(_row_value(row, "period_start")),
        observation_count=int(_row_value(row, "observation_count") or 0),
        delayed_count=int(_row_value(row, "delayed_count") or 0),
        delayed_ratio=float(_row_value(row, "delayed_ratio") or 0),
        average_delay_seconds=float(_row_value(row, "average_delay_seconds") or 0),
    )


def _problematic_stop_from_row(row: Any) -> ProblematicStop:
    return ProblematicStop(
        stop_id=str(_row_value(row, "stop_id") or ""),
        stop_name=str(_row_value(row, "stop_name") or ""),
        headsign=str(_row_value(row, "headsign") or "unknown"),
        observation_count=int(_row_value(row, "observation_count") or 0),
        average_delay_seconds=float(_row_value(row, "average_delay_seconds") or 0),
        delayed_ratio=float(_row_value(row, "delayed_ratio") or 0),
        major_delay_count=int(_row_value(row, "major_delay_count") or 0),
    )


def _predicted_delay_by_station_from_row(row: Any) -> PredictedDelayByStation:
    return PredictedDelayByStation(
        stop_id=str(_row_value(row, "stop_id") or ""),
        stop_name=str(_row_value(row, "stop_name") or ""),
        headsign=str(_row_value(row, "headsign") or "unknown"),
        prediction_time=_as_datetime(_row_value(row, "prediction_time")),
        predicted_delay_seconds=float(
            _row_value(row, "predicted_delay_seconds") or 0
        ),
    )


def _build_bigquery_client(config: AppConfig) -> Any:
    if bigquery is None:
        raise BigQueryRepositoryError(
            "google-cloud-bigquery is required when USE_BIGQUERY=true."
        )

    return bigquery.Client(project=config.gcp_project_id or None)


def _format_bigquery_init_error(exc: Exception) -> str:
    if isinstance(exc, DefaultCredentialsError):
        return f"Application Default Credentials are missing or unavailable: {exc}"
    return str(exc)


def _project_id(config: AppConfig, client: Optional[Any]) -> str:
    project_id = config.gcp_project_id or str(getattr(client, "project", "") or "")
    if not project_id:
        raise BigQueryRepositoryError("GCP_PROJECT_ID is required for BigQuery.")
    if not _GCP_PROJECT.match(project_id):
        raise BigQueryRepositoryError(f"Invalid GCP project id: {project_id}")
    return project_id


def _validate_bigquery_identifier(value: str, label: str) -> str:
    if not _BQ_IDENTIFIER.match(value):
        raise BigQueryRepositoryError(f"Invalid {label}: {value}")
    return value


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return getattr(row, key, None)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _truncate_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


def _is_tram_4_6_observation(observation: DelayObservation) -> bool:
    route_id = re.sub(r"[^0-9]", "", observation.route_id)
    return route_id in TRAM_4_6_ROUTE_IDS


def _normalized_headsign(value: str) -> str:
    headsign = value.strip() or "unknown"
    if headsign.lower() in _MORICZ_UJBUDA_HEADSIGNS:
        return MORICZ_UJBUDA_HEADSIGN
    return headsign


def _average_delay(observations: Sequence[DelayObservation]) -> float:
    if not observations:
        return 0.0
    return sum(observation.delay_seconds for observation in observations) / len(
        observations
    )


def _delayed_ratio(observations: Sequence[DelayObservation]) -> float:
    if not observations:
        return 0.0
    return sum(1 for observation in observations if observation.delay_seconds > 60) / len(
        observations
    )


def _group_by(
    observations: Sequence[DelayObservation],
    key_func: Callable[[DelayObservation], T],
) -> list[tuple[T, list[DelayObservation]]]:
    grouped: dict[T, list[DelayObservation]] = {}
    for observation in observations:
        grouped.setdefault(key_func(observation), []).append(observation)

    return sorted(
        grouped.items(),
        key=lambda item: item[0]
        if isinstance(item[0], (int, str, datetime, tuple))
        else "",
    )
