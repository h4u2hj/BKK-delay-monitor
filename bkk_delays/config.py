"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_BKK_API_BASE_URL = "https://futar.bkk.hu/api/query/v1/ws"

_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class AppConfig:
    bkk_api_key: str
    bkk_api_base_url: str
    gcp_project_id: str
    bigquery_dataset: str
    bigquery_table: str
    use_postgres: bool
    use_bigquery: bool
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_schema: str = "transit_data"
    postgres_sslmode: str = "prefer"
    bkk_api_dialect: str = "mobile"
    bkk_api_version: str = "2"
    bkk_api_timeout_seconds: float = 5.0
    postgres_connect_timeout_seconds: float = 8.0


def load_config() -> AppConfig:
    """Load app settings from .env and process environment variables."""

    load_dotenv()

    return AppConfig(
        bkk_api_key=os.getenv("BKK_API_KEY", "").strip(),
        bkk_api_base_url=os.getenv("BKK_API_BASE_URL", DEFAULT_BKK_API_BASE_URL).strip()
                         or DEFAULT_BKK_API_BASE_URL,
        gcp_project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
        bigquery_dataset=os.getenv("BIGQUERY_DATASET", "bkk_dw").strip()
                         or "bkk_dw",
        bigquery_table=os.getenv("BIGQUERY_TABLE", "delay_observations").strip()
                       or "delay_observations",
        use_postgres=_env_bool("USE_POSTGRES", False),
        use_bigquery=_env_bool("USE_BIGQUERY", False),
        postgres_host=os.getenv("POSTGRES_HOST", "").strip(),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "").strip(),
        postgres_user=os.getenv("POSTGRES_USER", "").strip(),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "").strip(),
        postgres_schema=os.getenv("POSTGRES_SCHEMA", "transit_data").strip()
                        or "transit_data",
        postgres_sslmode=os.getenv("POSTGRES_SSLMODE", "prefer").strip() or "prefer",
        bkk_api_dialect=os.getenv("BKK_API_DIALECT", "mobile").strip() or "mobile",
        bkk_api_version=os.getenv("BKK_API_VERSION", "2").strip() or "2",
        bkk_api_timeout_seconds=float(os.getenv("BKK_API_TIMEOUT_SECONDS", "5")),
        postgres_connect_timeout_seconds=float(
            os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "8")
        ),
    )
