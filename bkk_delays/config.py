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
    google_application_credentials: str
    use_firestore: bool
    use_bigquery: bool
    use_sample_data: bool
    bkk_api_dialect: str = "mobile"
    bkk_api_version: str = "2"
    bkk_api_timeout_seconds: float = 5.0
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_project_id: str = ""
    firebase_storage_bucket: str = ""
    firebase_messaging_sender_id: str = ""
    firebase_app_id: str = ""
    firebase_measurement_id: str = ""

    @property
    def firebase_web_config(self) -> dict[str, str]:
        """Return Firebase web SDK config values that are safe for the browser."""

        config = {
            "apiKey": self.firebase_api_key,
            "authDomain": self.firebase_auth_domain,
            "projectId": self.firebase_project_id,
            "storageBucket": self.firebase_storage_bucket,
            "messagingSenderId": self.firebase_messaging_sender_id,
            "appId": self.firebase_app_id,
            "measurementId": self.firebase_measurement_id,
        }
        return {key: value for key, value in config.items() if value}


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
        google_application_credentials=os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS", ""
        ).strip(),
        use_firestore=_env_bool("USE_FIRESTORE", False),
        use_bigquery=_env_bool("USE_BIGQUERY", False),
        use_sample_data=_env_bool("USE_SAMPLE_DATA", True),
        bkk_api_dialect=os.getenv("BKK_API_DIALECT", "mobile").strip() or "mobile",
        bkk_api_version=os.getenv("BKK_API_VERSION", "2").strip() or "2",
        bkk_api_timeout_seconds=float(os.getenv("BKK_API_TIMEOUT_SECONDS", "5")),
        firebase_api_key=os.getenv("FIREBASE_API_KEY", "").strip(),
        firebase_auth_domain=os.getenv("FIREBASE_AUTH_DOMAIN", "").strip(),
        firebase_project_id=os.getenv("FIREBASE_PROJECT_ID", "").strip(),
        firebase_storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET", "").strip(),
        firebase_messaging_sender_id=os.getenv(
            "FIREBASE_MESSAGING_SENDER_ID", ""
        ).strip(),
        firebase_app_id=os.getenv("FIREBASE_APP_ID", "").strip(),
        firebase_measurement_id=os.getenv("FIREBASE_MEASUREMENT_ID", "").strip(),
    )
