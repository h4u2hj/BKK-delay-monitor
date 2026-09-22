"""BigQuery analytics reads for the BKK delay warehouse dashboard view."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TypeVar
from zoneinfo import ZoneInfo

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from bkk_delays.config import AppConfig
from bkk_delays.models import DelayObservation, Stop

ANALYTICS_QUERY_FILE = (
    Path(__file__).resolve().parent.parent / "sql" / "bigquery_analytics_queries.sql"
)
QUERY_NAME_PATTERN = re.compile(r"^--\s*name:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$")
DASHBOARD_VIEW = "v_delay_dashboard"
DELAY_OBSERVATIONS_TABLE = "delay_observations"
DELAY_PREDICTION_MODEL = "delay_predictor_by_station_time"

_BQ_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GCP_PROJECT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*[A-Za-z0-9]$")
_BUDAPEST_TZ = ZoneInfo("Europe/Budapest")
MORICZ_UJBUDA_HEADSIGN = "Újbuda-központ M / Móricz Zsigmond körtér M"
_MORICZ_UJBUDA_HEADSIGNS = {
    "ujbuda-kozpont m",
    "moricz zsigmond korter m",
}
_DELAY_CATEGORY_ORDER = {
    "on time": 1,
    "minor delay": 2,
    "significant delay": 3,
    "severe delay": 4,
}


class BigQueryRepositoryError(RuntimeError):
    """Raised when BigQuery analytics cannot complete."""


@dataclass(frozen=True)
class KpiSummary:
    avg_delay_minutes: float = 0.0
    max_delay_minutes: float = 0.0
    observation_count: int = 0
    delayed_ratio: float = 0.0
    significant_or_severe_count: int = 0


@dataclass(frozen=True)
class StopDelayRanking:
    stop_name: str
    headsign: str
    avg_delay_minutes: float
    significant_or_severe_count: int
    observation_count: int


@dataclass(frozen=True)
class DailyDelayTrend:
    calendar_date: date
    route_number: str
    avg_delay_minutes: float
    observation_count: int


@dataclass(frozen=True)
class HourlyDelayTrend:
    observed_hour: int
    avg_delay_minutes: float
    observation_count: int


@dataclass(frozen=True)
class DelayCategoryBreakdown:
    delay_category: str
    observation_count: int


@dataclass(frozen=True)
class TimePeriodDelayMatrix:
    route_number: str
    time_period: str
    avg_delay_minutes: float
    observation_count: int


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
    kpi_summary: Optional[KpiSummary] = None
    stop_delay_ranking: tuple[StopDelayRanking, ...] = ()
    daily_delay_trend: tuple[DailyDelayTrend, ...] = ()
    hourly_delay_trend: tuple[HourlyDelayTrend, ...] = ()
    delay_category_breakdown: tuple[DelayCategoryBreakdown, ...] = ()
    time_period_delay_matrix: tuple[TimePeriodDelayMatrix, ...] = ()
    average_delay_by_stop: tuple[AverageDelayByStop, ...] = ()
    delayed_ratio_by_period: tuple[DelayedRatioByPeriod, ...] = ()
    most_problematic_stops: tuple[ProblematicStop, ...] = ()
    predicted_delay_by_station: tuple[PredictedDelayByStation, ...] = ()

    @property
    def has_dashboard_statistics(self) -> bool:
        return bool(
            (self.kpi_summary and self.kpi_summary.observation_count)
            or self.stop_delay_ranking
            or self.daily_delay_trend
            or self.hourly_delay_trend
            or self.delay_category_breakdown
            or self.time_period_delay_matrix
        )

    @property
    def has_legacy_statistics(self) -> bool:
        return bool(
            self.average_delay_by_stop
            or self.delayed_ratio_by_period
            or self.most_problematic_stops
            or self.predicted_delay_by_station
        )

    @property
    def max_stop_avg_delay_minutes(self) -> float:
        return max(
            (row.avg_delay_minutes for row in self.stop_delay_ranking),
            default=0.0,
        )

    @property
    def max_daily_avg_delay_minutes(self) -> float:
        return max(
            (row.avg_delay_minutes for row in self.daily_delay_trend),
            default=0.0,
        )

    @property
    def max_hourly_avg_delay_minutes(self) -> float:
        return max(
            (row.avg_delay_minutes for row in self.merged_hourly_delay_trend),
            default=0.0,
        )

    @property
    def merged_hourly_delay_trend(self) -> tuple[HourlyDelayTrend, ...]:
        return _normalize_hourly_delay_trend(self.hourly_delay_trend)

    @property
    def max_category_observation_count(self) -> int:
        return max(
            (row.observation_count for row in self.delay_category_breakdown),
            default=0,
        )

    @property
    def time_period_columns(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {row.time_period for row in self.time_period_delay_matrix},
                key=lambda value: (_time_period_sort_order(value), value),
            )
        )

    @property
    def time_period_route_numbers(self) -> tuple[str, ...]:
        return tuple(
            sorted({row.route_number for row in self.time_period_delay_matrix})
        )

    def time_period_value(
        self,
        route_number: str,
        time_period: str,
    ) -> Optional[TimePeriodDelayMatrix]:
        for row in self.time_period_delay_matrix:
            if row.route_number == route_number and row.time_period == time_period:
                return row
        return None


T = TypeVar("T")


class BigQueryRepository:
    """Read analytics from the BigQuery warehouse dashboard view."""

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
        """Read all warehouse dashboard statistics for the Flask page."""

        if not self.config.use_bigquery:
            return empty_statistics()

        return BigQueryStatistics(
            kpi_summary=self.kpi_summary(),
            stop_delay_ranking=tuple(self.stop_delay_ranking()),
            daily_delay_trend=tuple(self.daily_delay_trend()),
            hourly_delay_trend=tuple(self.hourly_delay_trend()),
            delay_category_breakdown=tuple(self.delay_category_breakdown()),
            time_period_delay_matrix=tuple(self.time_period_delay_matrix()),
        )

    def kpi_summary(self) -> KpiSummary:
        rows = self._query_rows(
            self._render_query("kpi_summary"),
            _kpi_summary_from_row,
        )
        return rows[0] if rows else KpiSummary()

    def stop_delay_ranking(self) -> list[StopDelayRanking]:
        return self._query_rows(
            self._render_query("stop_delay_ranking"),
            _stop_delay_ranking_from_row,
        )

    def daily_delay_trend(self) -> list[DailyDelayTrend]:
        return self._query_rows(
            self._render_query("daily_delay_trend"),
            _daily_delay_trend_from_row,
        )

    def hourly_delay_trend(self) -> list[HourlyDelayTrend]:
        rows = self._query_rows(
            self._render_query("hourly_delay_trend"),
            _hourly_delay_trend_from_row,
        )
        return list(_normalize_hourly_delay_trend(rows))

    def delay_category_breakdown(self) -> list[DelayCategoryBreakdown]:
        return self._query_rows(
            self._render_query("delay_category_breakdown"),
            _delay_category_breakdown_from_row,
        )

    def time_period_delay_matrix(self) -> list[TimePeriodDelayMatrix]:
        return self._query_rows(
            self._render_query("time_period_delay_matrix"),
            _time_period_delay_matrix_from_row,
        )

    def _query_rows(
        self,
        sql: str,
        mapper: Callable[[Any], T],
    ) -> list[T]:
        client = self._require_client()

        try:
            rows = client.query(sql).result()
            return [mapper(row) for row in rows]
        except Exception as exc:
            raise BigQueryRepositoryError(
                f"BigQuery analytics query failed: {exc}"
            ) from exc

    def _dashboard_view_id(self) -> str:
        return self._table_id(DASHBOARD_VIEW)

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

        return query_template.format(dashboard_view=self._dashboard_view_id())

    def _require_client(self) -> Any:
        if self._client is not None:
            return self._client

        message = self._init_error or "BigQuery client is not configured."
        raise BigQueryRepositoryError(message)


def statistics_from_observations(
    observations: Sequence[DelayObservation],
    stops: Sequence[Stop] = (),
) -> BigQueryStatistics:
    """Build a small dashboard snapshot from in-memory observations."""

    stop_names = {stop.id: stop.name for stop in stops}
    observations = [
        observation
        for observation in observations
        if _is_tram_4_6_observation(observation)
    ]
    if not observations:
        return empty_statistics()

    stop_groups = _group_by(
        observations,
        lambda observation: (
            observation.stop_id,
            stop_names.get(observation.stop_id, observation.stop_id),
            _normalized_headsign(observation.headsign),
        ),
    )
    period_groups = _group_by(
        observations,
        lambda observation: _truncate_hour(observation.scheduled_departure),
    )

    stop_delay_ranking = tuple(
        sorted(
            (
                StopDelayRanking(
                    stop_name=stop_key[1],
                    headsign=stop_key[2],
                    avg_delay_minutes=_average_delay_minutes(stop_observations),
                    significant_or_severe_count=sum(
                        1
                        for observation in stop_observations
                        if _is_significant_or_severe(observation)
                    ),
                    observation_count=len(stop_observations),
                )
                for stop_key, stop_observations in stop_groups
            ),
            key=lambda row: (
                row.avg_delay_minutes,
                row.significant_or_severe_count,
            ),
            reverse=True,
        )[:10]
    )

    return BigQueryStatistics(
        kpi_summary=KpiSummary(
            avg_delay_minutes=_average_delay_minutes(observations),
            max_delay_minutes=round(
                max(observation.delay_seconds for observation in observations) / 60,
                2,
            ),
            observation_count=len(observations),
            delayed_ratio=_delayed_ratio(observations),
            significant_or_severe_count=sum(
                1
                for observation in observations
                if _is_significant_or_severe(observation)
            ),
        ),
        stop_delay_ranking=stop_delay_ranking,
        daily_delay_trend=_daily_trend_from_observations(observations),
        hourly_delay_trend=_hourly_trend_from_observations(observations),
        delay_category_breakdown=_category_breakdown_from_observations(observations),
        time_period_delay_matrix=_time_period_matrix_from_observations(observations),
        average_delay_by_stop=tuple(
            AverageDelayByStop(
                stop_id=stop_key[0],
                stop_name=stop_key[1],
                headsign=stop_key[2],
                observation_count=len(stop_observations),
                average_delay_seconds=_average_delay(stop_observations),
            )
            for stop_key, stop_observations in stop_groups
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
            for period, period_observations in period_groups
        ),
        most_problematic_stops=tuple(
            ProblematicStop(
                stop_id=stop_key[0],
                stop_name=stop_key[1],
                headsign=stop_key[2],
                observation_count=len(stop_observations),
                average_delay_seconds=_average_delay(stop_observations),
                delayed_ratio=_delayed_ratio(stop_observations),
                major_delay_count=sum(
                    1
                    for observation in stop_observations
                    if _is_significant_or_severe(observation)
                ),
            )
            for stop_key, stop_observations in stop_groups
        ),
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
    return BigQueryStatistics()


def _strip_trailing_semicolon(sql: str) -> str:
    return sql[:-1].rstrip() if sql.endswith(";") else sql


def _kpi_summary_from_row(row: Any) -> KpiSummary:
    return KpiSummary(
        avg_delay_minutes=float(_row_value(row, "avg_delay_minutes") or 0),
        max_delay_minutes=float(_row_value(row, "max_delay_minutes") or 0),
        observation_count=int(_row_value(row, "observation_count") or 0),
        delayed_ratio=float(_row_value(row, "delayed_ratio") or 0),
        significant_or_severe_count=int(
            _row_value(row, "significant_or_severe_count") or 0
        ),
    )


def _stop_delay_ranking_from_row(row: Any) -> StopDelayRanking:
    return StopDelayRanking(
        stop_name=str(_row_value(row, "stop_name") or ""),
        headsign=str(_row_value(row, "headsign") or "unknown"),
        avg_delay_minutes=float(_row_value(row, "avg_delay_minutes") or 0),
        significant_or_severe_count=int(
            _row_value(row, "significant_or_severe_count") or 0
        ),
        observation_count=int(_row_value(row, "observation_count") or 0),
    )


def _daily_delay_trend_from_row(row: Any) -> DailyDelayTrend:
    return DailyDelayTrend(
        calendar_date=_as_date(_row_value(row, "calendar_date")),
        route_number=str(_row_value(row, "route_number") or ""),
        avg_delay_minutes=float(_row_value(row, "avg_delay_minutes") or 0),
        observation_count=int(_row_value(row, "observation_count") or 0),
    )


def _hourly_delay_trend_from_row(row: Any) -> HourlyDelayTrend:
    return HourlyDelayTrend(
        observed_hour=int(_row_value(row, "observed_hour") or 0),
        avg_delay_minutes=float(_row_value(row, "avg_delay_minutes") or 0),
        observation_count=int(_row_value(row, "observation_count") or 0),
    )


def _normalize_hourly_delay_trend(
    rows: Sequence[HourlyDelayTrend],
) -> tuple[HourlyDelayTrend, ...]:
    if not rows:
        return ()

    weighted_delay_by_hour: dict[int, float] = {}
    count_by_hour: dict[int, int] = {}

    for row in rows:
        hour = min(max(row.observed_hour, 0), 23)
        observation_count = max(row.observation_count, 0)
        weighted_delay_by_hour[hour] = weighted_delay_by_hour.get(hour, 0.0) + (
            row.avg_delay_minutes * observation_count
        )
        count_by_hour[hour] = count_by_hour.get(hour, 0) + observation_count

    return tuple(
        HourlyDelayTrend(
            observed_hour=hour,
            avg_delay_minutes=round(
                weighted_delay_by_hour.get(hour, 0.0) / count_by_hour[hour],
                2,
            )
            if count_by_hour.get(hour, 0)
            else 0.0,
            observation_count=count_by_hour.get(hour, 0),
        )
        for hour in range(24)
    )


def _delay_category_breakdown_from_row(row: Any) -> DelayCategoryBreakdown:
    return DelayCategoryBreakdown(
        delay_category=str(_row_value(row, "delay_category") or "unknown"),
        observation_count=int(_row_value(row, "observation_count") or 0),
    )


def _time_period_delay_matrix_from_row(row: Any) -> TimePeriodDelayMatrix:
    return TimePeriodDelayMatrix(
        route_number=str(_row_value(row, "route_number") or ""),
        time_period=str(_row_value(row, "time_period") or "unknown"),
        avg_delay_minutes=float(_row_value(row, "avg_delay_minutes") or 0),
        observation_count=int(_row_value(row, "observation_count") or 0),
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


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    return date.min


def _truncate_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


def _is_tram_4_6_observation(observation: DelayObservation) -> bool:
    return _route_number_from_route_id(observation.route_id) in {"4", "6"}


def _route_number_from_route_id(route_id: str) -> str:
    route_id = route_id.strip()
    digits = re.sub(r"[^0-9]", "", route_id)
    if digits in {"3040", "4"} or digits.endswith("3040"):
        return "4"
    if digits in {"3060", "6"} or digits.endswith("3060"):
        return "6"
    match = re.search(r"(?:^|[^0-9])([46])$", route_id)
    return match.group(1) if match else ""


def _normalized_headsign(value: str) -> str:
    headsign = value.strip() or "unknown"
    if _normalize_text(headsign) in _MORICZ_UJBUDA_HEADSIGNS:
        return MORICZ_UJBUDA_HEADSIGN
    return headsign


def _normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).lower()


def _average_delay(observations: Sequence[DelayObservation]) -> float:
    if not observations:
        return 0.0
    return sum(observation.delay_seconds for observation in observations) / len(
        observations
    )


def _average_delay_minutes(observations: Sequence[DelayObservation]) -> float:
    return round(_average_delay(observations) / 60, 2)


def _delayed_ratio(observations: Sequence[DelayObservation]) -> float:
    if not observations:
        return 0.0
    return sum(1 for observation in observations if observation.delay_seconds > 60) / len(
        observations
    )


def _display_delay_category(observation: DelayObservation) -> str:
    source_category = observation.delay_category.strip().lower().replace("_", " ")
    if source_category in _DELAY_CATEGORY_ORDER:
        return source_category
    if source_category == "major delay":
        return "significant delay"
    if observation.delay_seconds <= 60:
        return "on time"
    if observation.delay_seconds <= 180:
        return "minor delay"
    if observation.delay_seconds <= 300:
        return "significant delay"
    return "severe delay"


def _is_significant_or_severe(observation: DelayObservation) -> bool:
    return _display_delay_category(observation) in {
        "significant delay",
        "severe delay",
    }


def _time_period(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(_BUDAPEST_TZ)
    if 6 <= value.hour <= 9:
        return "morning peak"
    if 15 <= value.hour <= 18:
        return "afternoon peak"
    return "other period"


def _time_period_sort_order(value: str) -> int:
    return {
        "morning peak": 1,
        "afternoon peak": 2,
        "other period": 3,
    }.get(value, 99)


def _daily_trend_from_observations(
    observations: Sequence[DelayObservation],
) -> tuple[DailyDelayTrend, ...]:
    return tuple(
        DailyDelayTrend(
            calendar_date=trend_key[0],
            route_number=trend_key[1],
            avg_delay_minutes=_average_delay_minutes(trend_observations),
            observation_count=len(trend_observations),
        )
        for trend_key, trend_observations in _group_by(
            observations,
            lambda observation: (
                observation.created_at.date(),
                _route_number_from_route_id(observation.route_id),
            ),
        )
    )


def _hourly_trend_from_observations(
    observations: Sequence[DelayObservation],
) -> tuple[HourlyDelayTrend, ...]:
    grouped = {
        hour_key: hour_observations
        for hour_key, hour_observations in _group_by(
            observations,
            lambda observation: observation.created_at.astimezone(_BUDAPEST_TZ).hour
            if observation.created_at.tzinfo
            else observation.created_at.hour,
        )
    }

    return tuple(
        HourlyDelayTrend(
            observed_hour=hour,
            avg_delay_minutes=_average_delay_minutes(grouped.get(hour, ())),
            observation_count=len(grouped.get(hour, ())),
        )
        for hour in range(24)
    )


def _category_breakdown_from_observations(
    observations: Sequence[DelayObservation],
) -> tuple[DelayCategoryBreakdown, ...]:
    rows = tuple(
        DelayCategoryBreakdown(
            delay_category=category,
            observation_count=len(category_observations),
        )
        for category, category_observations in _group_by(
            observations,
            _display_delay_category,
        )
    )
    return tuple(
        sorted(
            rows,
            key=lambda row: _DELAY_CATEGORY_ORDER.get(row.delay_category, 5),
        )
    )


def _time_period_matrix_from_observations(
    observations: Sequence[DelayObservation],
) -> tuple[TimePeriodDelayMatrix, ...]:
    return tuple(
        TimePeriodDelayMatrix(
            route_number=period_key[0],
            time_period=period_key[1],
            avg_delay_minutes=_average_delay_minutes(period_observations),
            observation_count=len(period_observations),
        )
        for period_key, period_observations in _group_by(
            observations,
            lambda observation: (
                _route_number_from_route_id(observation.route_id),
                _time_period(observation.scheduled_departure),
            ),
        )
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
        if isinstance(item[0], (int, str, date, datetime, tuple))
        else "",
    )
