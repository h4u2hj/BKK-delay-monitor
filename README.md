# BKK Delay Monitor

A minimal Flask web application scaffold for a BKK delay monitoring and analytics coursework project.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python -m bkk_delays
```

The app is also runnable with Flask:

```powershell
.\.venv\Scripts\flask --app bkk_delays.app run --debug
```

## Current Features

- Search page with live BKK/FUTAR station lookup after more than 3 typed characters.
- Station selection stores the FUTAR stop ID in the form as `station_id`.
- Optional Firestore persistence for normalized search collection batches.
- Optional BigQuery analytics reads from normalized tables.
- History tab for Firestore-backed observation browsing.
- Statistics tab backed by BigQuery.
- Minimal custom CSS with responsive layout.

## Firestore Credentials

Keep `USE_FIRESTORE=false` to use search only. If `USE_FIRESTORE=true`,
the app uses Google Application Default Credentials for Firestore.

User ADC through gcloud:

```powershell
gcloud auth application-default login
```

## BigQuery Analytics

Keep `USE_BIGQUERY=false` to turn off statistics. The statistics page will then
not be available. The page is titled `4-6 statistics` and filters analytics to tram 4 and 6 route IDs `BKK_3040`
and `BKK_3060`. To read analytics from BigQuery, set:

```powershell
USE_BIGQUERY=true
GCP_PROJECT_ID=
BIGQUERY_DATASET=
```

The repository reads these normalized table names in the configured dataset:

- `routes`
- `stops`
- `collection_runs`
- `delay_observations`

Analytics SQL is kept in `sql/bigquery_analytics_queries.sql`. The Python
repository only validates table identifiers, renders those table names into the
queries, binds query parameters, and maps result rows for the statistics page.
Station-level statistics group by both station and `headsign`, so the same stop
can appear once per direction. `Újbuda-központ M` and `Móricz Zsigmond körtér M`
headsigns are grouped together as one direction. The delayed-ratio time period
statistic is bucketed by scheduled departure time, not by when the prediction was
searched.

For credentials, the app relies on Application Default Credentials from `gcloud
auth application-default login` or the runtime environment. The authenticated
principal needs permission to run BigQuery jobs and read the configured
dataset/tables for the app's current BigQuery usage. Station search and
collection do not write to BigQuery; Firestore remains the operational
persistence path.
