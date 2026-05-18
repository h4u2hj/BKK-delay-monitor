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

## Scheduled Cloud Function

The scheduled collector entry point is `collect_bkk_data` in `main.py`. Deploy it
as a Cloud Run Function with the function name passed as the entry point, not as
the container command:

```powershell
gcloud functions deploy collect_bkk_data `
  --gen2 `
  --runtime=python312 `
  --region=europe-west1 `
  --source=. `
  --entry-point=collect_bkk_data `
  --trigger-topic=<pubsub-topic>
```

If deploying the same source directly as a Cloud Run service, the included
`Procfile` starts Functions Framework with `collect_bkk_data` as the target.
Do not set the Cloud Run container command to `collect_bkk_data`; that makes the
container shell look for an executable with that name and exits with code 127.

For buildpack-based Cloud Run function builds, the function target has to be
passed through the buildpack environment variable names:

```text
GOOGLE_FUNCTION_TARGET=collect_bkk_data
GOOGLE_FUNCTION_SIGNATURE_TYPE=cloudevent
GOOGLE_FUNCTION_SOURCE=main.py
GOOGLE_RUNTIME_VERSION=3.14.0
```

Cloud Build trigger substitutions such as `_FUNCTION_TARGET` are only template
variables. They do not configure Functions Framework unless the build command
maps them into the `GOOGLE_FUNCTION_*` build environment variables. The
repository includes `project.toml` so Google Cloud buildpacks receive these
settings during remote builds.

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
