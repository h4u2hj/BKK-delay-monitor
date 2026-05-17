# BKK Delay Monitor - Coding Agent Development Plan

## Project Goal

Build an MSc coursework information system for monitoring and analyzing BKK/FUTAR public transport delay predictions. The application must be a working Python Flask web app with a simple Bootstrap GUI, a controlled set of monitored stops on tram lines 4 and 6, data collection from the BKK/FUTAR API, delay normalization, persistence, and BigQuery-based analytics.

The system collects predicted departure observations, not final realized departure events. Duplicates are expected because the same trip can appear in multiple consecutive API calls.

## Current Repository State

The repository currently contains the completed Phase 1 Flask scaffold:

- `pyproject.toml`
- `dev-requirements.txt`
- `.env.example`
- `.gitignore`
- `README.md`
- `bkk_delays/__main__.py`
- `bkk_delays/__init__.py`
- `bkk_delays/app.py`
- `bkk_delays/templates/base.html`
- `bkk_delays/templates/index.html`
- `bkk_delays/templates/history.html`
- `bkk_delays/static/css/app.css`
- `tests/test_app.py`

The Python package directory is already named `bkk_delays`, which is import-safe. The distribution name in `pyproject.toml` is `bkk-delay-monitor`, which is acceptable because package/distribution names may contain hyphens.

Current UI state:

- `/` shows a minimal station search screen with a centered search field and an inactive `Get` button.
- `/history` shows an empty Firestore history page placeholder.
- The header has centered tabs for `Search` and `History`.
- The visual accent color is purple.
- The search bar is intentionally placed slightly above vertical center on desktop.
- Station lookup now fetches departure predictions and the BKK API adapter returns database-ready `routes`, `stops`, `collection_runs`, and `delay_observations` entities directly. The UI displays the same departure table fields as before plus `delay_seconds`.

Current verification:

- `python -m pytest -q` passes.
- `python -m ruff check .` passes.
- `/` and `/history` render successfully in Flask.

## Target Architecture

Use a modular Flask application with this intended structure:

```text
bkk-delays_project/
  pyproject.toml
  dev-requirements.txt
  .env.example
  README.md
  CODING_AGENTS_PLAN.md
  bkk_delays/
    __init__.py
    __main__.py
    app.py
    config.py
    bkk_api.py
    delay_processor.py
    firestore_repository.py
    bigquery_repository.py
    collect_bkk_data.py
    models.py
    sample_data.py
    logging_config.py
    templates/
      base.html
      index.html
      collect.html
      observations.html
      statistics.html
      logs.html
    static/
      css/
        app.css
  tests/
    test_delay_processor.py
    test_sample_data.py
```

Data flow clarification:

- The Flask app and collection workflow write normalized observations to Firestore as the operational store.
- BigQuery is populated outside the app by a Firestore-to-BigQuery sync configured in GCP.
- The app treats BigQuery as read-only and uses it only for analytics queries shown in `/statistics`.
- The statistics page is specifically for tram 4 and 6, using BigQuery `route_id` values `BKK_3040` and `BKK_3060`.

## Development Phases

### Phase 1 - Project Foundation

Status: completed for the local Flask scaffold.

Tasks:

- Rename `bkk-delays/` to `bkk_delays/`. Done.
- Update `pyproject.toml` metadata, dependencies, package discovery, and CLI entry point. Done.
- Add initial runtime dependencies. Done:
  - `Flask`
  - `requests`
  - `python-dotenv`
- Add cloud dependencies later when the persistence phase begins:
  - `google-cloud-firestore`
  - `google-cloud-bigquery`
  - `google-auth`
- Keep dev dependencies focused. Done:
  - `pytest`
- `ruff`
- Add `.env.example` with all required configuration keys. Done.
- Add `README.md` with local setup and run commands. Done.
- Add a simple Flask web UI. Done:
  - Search tab at `/`
  - History tab at `/history`
  - Minimal responsive custom CSS
  - Purple accent color
  - Inactive `Get` button for the future station lookup flow

Acceptance criteria:

- `python -m bkk_delays` starts the app. Done.
- `flask --app bkk_delays.app run` can start the web app once dependencies are installed. Done.
- The project imports cleanly with `import bkk_delays`. Done.
- Search and History pages return HTTP 200. Done.
- Basic route smoke tests exist. Done.

Useful commands:

```powershell
.\.venv\Scripts\python -m bkk_delays
.\.venv\Scripts\python -m flask --app bkk_delays.app run --debug
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check .
```

### Phase 2 - Configuration and Domain Model

Tasks:

- Implement `config.py` with environment-based settings:
  - `BKK_API_KEY`
  - `BKK_API_BASE_URL`
  - `GCP_PROJECT_ID`
  - `BIGQUERY_DATASET`
  - `BIGQUERY_TABLE`
  - `GOOGLE_APPLICATION_CREDENTIALS`
  - `USE_FIRESTORE`
  - `USE_BIGQUERY`
  - `USE_SAMPLE_DATA`
- Implement `models.py` using dataclasses or typed dictionaries for:
  - `MonitoredStop`
  - `Route`
  - `Stop`
  - `CollectionRun`
  - `DelayObservation`
  - `SearchCollectionBatch`
  - `ApiCallLog`
- Define a fixed monitored stop list for tram 4-6 with 10-15 important stops across both directions.

Acceptance criteria:

- Configuration has safe defaults for local development.
- Missing cloud credentials do not crash the app when sample-data mode is enabled.
- Data fields match the planned Firestore and BigQuery schema.

### Phase 3 - BKK API Client

Tasks:

- Implement `bkk_api.py`.
- Keep all external API calls in this module.
- Add timeout handling, HTTP error handling, and structured call logs.
- Fetch departure predictions for the configured monitored stops.
- Convert stop departure responses directly into normalized entity batches; do not keep a separate stop-departure prediction model between the API adapter and Flask.
- Do not hard-code secrets.
- Keep API request rate modest because the project monitors only a limited set of stops.

Acceptance criteria:

- API failures return structured errors instead of crashing the whole collection run.
- The caller can distinguish successful stop calls, empty responses, and failed calls.
- The module can be mocked easily in tests.

Implementation caution:

- Confirm the exact BKK/FUTAR endpoint and response shape against the current official API documentation before final coding. Do not invent field paths if the live API differs.

### Phase 4 - Delay Processing

Tasks:

- Implement `delay_processor.py`.
- Normalize raw API records into database-ready entity batches without an intermediate departure prediction DTO.
- Extract:
  - `route_id`
  - `route_short_name`
  - `route_type`
  - `stop_id`
  - `stop_name`
  - `stop_lat`
  - `stop_lon`
  - `collection_run_id`
  - `collection_run.started_at`
  - `collection_run.finished_at`
  - `collection_run.status`
  - `collection_run.records_saved`
  - `collection_run.error_message`
  - `delay_observation.id`
  - `trip_id`
  - `headsign`
  - `direction_id`
  - `stop_sequence`
  - `scheduled_departure`
  - `predicted_departure`
  - `delay_seconds`
  - `delay_category`
  - `created_at`
- Use this formula:

```text
delay_seconds = predicted_departure - scheduled_departure
```

- Suggested delay categories:
  - `early`: less than -60 seconds
  - `on_time`: -60 to 60 seconds
  - `minor_delay`: 61 to 180 seconds
  - `medium_delay`: 181 to 360 seconds
  - `major_delay`: more than 360 seconds
- Generate a natural deduplication key:

```text
trip_id + stop_id + scheduled_departure
```

Acceptance criteria:

- Processor works from raw API data and from local sample data.
- Unit tests cover delay calculation, category assignment, entity creation, and later deduplication key generation when persistence is added.

### Phase 5 - Persistence Layer

Tasks:

- Implement `firestore_repository.py` for operational/raw writes:
  - `routes`
  - `stops`
  - `collection_runs`
  - `delay_observations`
  - `api_call_logs`
  - `raw_api_responses`
  - `monitored_stops`
- Configure the GCP Firestore-to-BigQuery sync outside this app so Firestore writes populate:
  - dataset: `bkk_analytics`
  - tables: `routes`, `stops`, `collection_runs`, `delay_observations`
- Implement `bigquery_repository.py` as a read-only analytics repository. It must not expose insert/update/save methods.
- Partition BigQuery by `created_at` in the GCP-managed sync or follow-up SQL setup.
- Cluster BigQuery by `route_id` and `stop_id` where supported.
- Make read repositories no-op or sample-backed when cloud configuration is disabled.

Acceptance criteria:

- Collection and station search save observations to Firestore only when persistence is enabled.
- Collection and station search never write directly to BigQuery.
- Duplicate Firestore observations do not break insertion.
- BigQuery read errors are logged with enough context to debug analytics failures.

### Phase 6 - Collection Workflow

Tasks:

- Implement `collect_bkk_data.py`.
- Collection flow:
  1. Load monitored stops.
  2. Call BKK API for each stop.
  3. Normalize predictions.
  4. Save raw logs if enabled.
  5. Save normalized observations to Firestore when enabled.
  6. Return a summary with counts and errors.
- Add a CLI command or module entry point for manual collection.
- Make the Flask GUI able to trigger one collection run manually.

Acceptance criteria:

- A single manual collection run produces a clear summary:
  - stops queried
  - API calls succeeded
  - API calls failed
  - observations generated
  - observations inserted
  - duplicates skipped if tracked
- Errors at one stop do not prevent other stops from being processed.

### Phase 7 - Flask GUI

Tasks:

- Implement `app.py` with routes:
  - `/` dashboard
  - `/collect` manual collection page and POST trigger
  - `/observations` latest observations
  - `/statistics` BigQuery analytics
  - `/logs` API call and collection logs
- Use Bootstrap templates under `templates/`.
- Keep the UI simple and functional, not a marketing page.
- Show sample-data warnings when running without cloud persistence.

Acceptance criteria:

- User can start data collection from the browser.
- User can inspect latest observations in a table.
- User can view basic statistics.
- User can inspect recent logs/errors.

### Phase 8 - BigQuery Analytics

Tasks:

- Treat BigQuery as read-only because GCP Firestore-to-BigQuery sync fills the analytics dataset.
- Keep BigQuery SQL query text in `sql/bigquery_analytics_queries.sql`; `bigquery_repository.py` should load and render named query blocks rather than storing SQL inline.
- Add query methods in `bigquery_repository.py` for:
  - average delay by stop and headsign
  - delayed ratio by time period
  - most problematic stops and headsign
- Surface these in `/statistics`.
- Title the statistics page `4-6 statistics`.
- Filter every BigQuery analytics query to `route_id` values `BKK_3040` and `BKK_3060`.
- Group station-level statistics by both station and `headsign` so both directions appear as separate rows.
- Group `Újbuda-központ M` and `Móricz Zsigmond körtér M` headsigns together as the same direction.
- Group delay-ratio time periods by `scheduled_departure`, not by the observation search time.
- If BigQuery is disabled, show sample analytics from generated sample observations.

Acceptance criteria:

- At least three meaningful statistics are visible in the GUI.
- SQL is readable and parameterized where needed.
- Statistics queries should not use result limits.
- Empty datasets produce friendly empty states.
- No station search, collection, or repository method writes directly to BigQuery.

### Phase 9 - Sample Data and Local Demo Mode

Tasks:

- Implement `sample_data.py`.
- Provide deterministic sample observations for development and grading demos.
- Ensure the app can run without real BKK API credentials or GCP credentials.
- Clearly label sample mode in the UI.

Acceptance criteria:

- Fresh checkout can run locally and demonstrate the main flows.
- Tests can run without network or cloud access.

### Phase 10 - Testing and Documentation

Tasks:

- Add focused unit tests for processing and sample analytics.
- Add README sections:
  - project purpose
  - architecture
  - setup
  - environment variables
  - local sample mode
  - real API/cloud mode
  - BigQuery schema
  - known duplicate behavior
  - limitations and future improvements
- Include coursework-specific explanation:
  - why Firestore is operational/raw storage
  - why BigQuery is analytical storage
  - what database concepts are demonstrated

Acceptance criteria:

- `pytest` passes.
- A reviewer can understand how to run the project locally.
- The documentation explicitly explains that the system stores prediction observations, not final departure facts.

## Database Schema

Target normalized entities:

Firestore is the application write source for these entities. BigQuery mirrors
the same normalized shape through the Firestore-to-BigQuery sync configured in
GCP, then serves analytics reads.

`routes`

```text
id STRING
short_name STRING
route_type STRING
```

`stops`

```text
id STRING
name STRING
lat FLOAT64
lon FLOAT64
```

`collection_runs`

```text
id STRING
started_at TIMESTAMP
finished_at TIMESTAMP
status STRING
records_saved INT64
error_message STRING
```

`delay_observations`

Fields:

```text
id STRING
collection_run_id STRING
route_id STRING
stop_id STRING
trip_id STRING
headsign STRING
direction_id STRING
stop_sequence INT64
scheduled_departure TIMESTAMP
predicted_departure TIMESTAMP
delay_seconds INT64
delay_category STRING
created_at TIMESTAMP
```

Recommended partitioning:

- Partition `delay_observations` by `created_at`.
- Partition `collection_runs` by `started_at` if the table grows.

Recommended clustering:

- `route_id`
- `stop_id`

## Firestore Collections

Suggested collections:

- `routes`: route dimension records.
- `stops`: stop dimension records.
- `collection_runs`: one record per lookup or collection run.
- `delay_observations`: normalized prediction observation facts.
- `api_call_logs`: API call status, timing, and errors.
- `raw_api_responses`: optional raw response snapshots for debugging.
- `monitored_stops`: configured tram 4-6 stops.

Firestore is the application write path. BigQuery is read-only in this app and
is filled by the GCP Firestore-to-BigQuery sync. Local sample mode remains the
fallback when cloud configuration is unavailable.

## GUI Requirements

Pages:

- Search page:
  - station search input centered on the page
  - inactive `Get` button until the BKK API integration is implemented
  - minimal purple-accent design
- History page:
  - empty Firestore placeholder for now
  - later backed by Firestore observations
- Future home/dashboard:
  - current mode
  - last collection summary
  - total recent observations
  - quick links
- Collection page:
  - manual trigger button
  - status summary
  - error list
- Observations page:
  - latest observations table
  - stop, route, direction, scheduled time, predicted time, delay seconds, delay category
- Statistics page:
  - title: `4-6 statistics`
  - average delay by stop and headsign
  - delay ratio by time period
  - problematic stops by stop and headsign
- Logs page:
  - recent collection/API logs

## Suggested Implementation Order for Coding Agents

Follow this order unless the user asks otherwise:

1. Fix package structure and dependencies.
2. Add config, models, and sample data.
3. Implement delay processing and unit tests.
4. Build Flask app with sample mode pages.
5. Add collection workflow with a mocked/sample client path.
6. Add real BKK API client.
7. Add Firestore repository and station/collection persistence.
8. Add read-only BigQuery repository and analytics queries.
9. Polish README and coursework explanation.

This order keeps the application demonstrable early, even before external credentials are available.

## Definition of Done

The project is done when:

- The Flask web app starts locally.
- The user can trigger a collection run from the GUI.
- Delay observations are normalized into the target schema.
- Latest observations are visible in the GUI.
- Statistics are visible in the GUI from BigQuery or sample data.
- The code handles missing credentials gracefully in sample mode.
- Tests pass for delay processing.
- README explains setup, architecture, schema, and duplicate semantics.

## Agent Constraints

- Keep changes scoped to this project.
- Do not commit secrets, credentials, or real `.env` values.
- Prefer typed, testable Python functions over logic embedded directly in Flask routes.
- Avoid network-dependent tests.
- Do not overload the BKK API; keep the monitored stop list small and requests sequential or modestly throttled.
- If exact BKK/FUTAR API response fields are uncertain, add a small adapter layer and document the assumption instead of spreading guessed field names across the codebase.
- Keep the GUI simple, readable, and usable for a coursework demo.
