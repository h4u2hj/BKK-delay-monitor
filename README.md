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
- History tab for future Firestore-backed observation browsing.
- Statistics tab backed by BigQuery or the latest in-memory station search.
- Minimal custom CSS with responsive layout.

## Firestore Credentials

Keep `USE_FIRESTORE=false` for local/sample mode. If `USE_FIRESTORE=true`,
the app needs Google Application Default Credentials for Firestore.

User ADC through gcloud:

```powershell
gcloud auth application-default login
```

If the browser callback or consent screen fails, retry with the no-browser flow
and paste the returned code into the terminal:

```powershell
gcloud auth application-default login --no-browser
```

Service account JSON for local development:

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\service-account.json"
```

Or put the same path in `.env` as `GOOGLE_APPLICATION_CREDENTIALS`. Do not
commit credential files or real `.env` values.

## Firebase Web Config

The Firebase web SDK config is read from `.env` with these keys:

```powershell
FIREBASE_API_KEY=
FIREBASE_AUTH_DOMAIN=
FIREBASE_PROJECT_ID=
FIREBASE_STORAGE_BUCKET=
FIREBASE_MESSAGING_SENDER_ID=
FIREBASE_APP_ID=
FIREBASE_MEASUREMENT_ID=
```

When these values are present, the base template initializes Firebase and
Analytics in the browser. These web config values do not replace
`GOOGLE_APPLICATION_CREDENTIALS` for server-side Firestore writes.

## BigQuery Analytics

Keep `USE_BIGQUERY=false` for local/sample mode. The statistics page will then
use the latest in-memory station search, if one exists. The page is titled
`4-6 statistics` and filters analytics to tram 4 and 6 route IDs `BKK_3040`
and `BKK_3060`. To read analytics from BigQuery, set:

```powershell
USE_BIGQUERY=true
GCP_PROJECT_ID=bkktransitapp
BIGQUERY_DATASET=bkk_analytics
GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
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

For credentials, you need either Application Default Credentials from `gcloud
auth application-default login` or a service account JSON file. The account only
needs permission to run BigQuery jobs and read the configured dataset/tables for
the app's current BigQuery usage. Station search and collection do not write to
BigQuery; Firestore remains the operational persistence path. Firebase web
config values do not grant server-side BigQuery access.
