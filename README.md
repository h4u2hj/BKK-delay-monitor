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
- History tab for future Firestore-backed observation browsing.
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
