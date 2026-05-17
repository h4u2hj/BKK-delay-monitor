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
    firestore_database_id: str
    bigquery_dataset: str
    bigquery_table: str
    use_firestore: bool
    use_bigquery: bool
    use_sample_data: bool
    bkk_api_dialect: str = "mobile"
    bkk_api_version: str = "2"
    bkk_api_timeout_seconds: float = 5.0
    firestore_timeout_seconds: float = 8.0


def load_config() -> AppConfig:
    """Load app settings from .env and process environment variables."""

    load_dotenv()

    return AppConfig(
        bkk_api_key=os.getenv("BKK_API_KEY", "").strip(),
        bkk_api_base_url=os.getenv("BKK_API_BASE_URL", DEFAULT_BKK_API_BASE_URL).strip()
                         or DEFAULT_BKK_API_BASE_URL,
        gcp_project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
        firestore_database_id=os.getenv("FIRESTORE_DATABASE_ID", "").strip(),
        bigquery_dataset=os.getenv("BIGQUERY_DATASET", "bkk_analytics").strip()
                         or "bkk_analytics",
        bigquery_table=os.getenv("BIGQUERY_TABLE", "delay_observations").strip()
                       or "delay_observations",
        use_firestore=_env_bool("USE_FIRESTORE", False),
        use_bigquery=_env_bool("USE_BIGQUERY", False),
        use_sample_data=_env_bool("USE_SAMPLE_DATA", True),
        bkk_api_dialect=os.getenv("BKK_API_DIALECT", "mobile").strip() or "mobile",
        bkk_api_version=os.getenv("BKK_API_VERSION", "2").strip() or "2",
        bkk_api_timeout_seconds=float(os.getenv("BKK_API_TIMEOUT_SECONDS", "5")),
        firestore_timeout_seconds=float(os.getenv("FIRESTORE_TIMEOUT_SECONDS", "8")),
    )
