-- PostgreSQL schema for the BKK delay monitor operational store.
-- Intended for Google Cloud SQL for PostgreSQL.
--
-- This file matches the final normalized schema:
-- stops, routes, collection_runs, and delay_observations.

BEGIN;

CREATE SCHEMA IF NOT EXISTS transit_data;

SET search_path TO transit_data, public;

CREATE TABLE IF NOT EXISTS stops (
    id text PRIMARY KEY,
    name text NOT NULL,
    lat double precision,
    lon double precision
);

CREATE TABLE IF NOT EXISTS routes (
    id text PRIMARY KEY,
    short_name text NOT NULL,
    route_type text NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_runs (
    id text PRIMARY KEY,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL,
    records_saved integer NOT NULL,
    error_message text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS delay_observations (
    id text PRIMARY KEY,
    collection_run_id text NOT NULL,
    route_id text NOT NULL,
    stop_id text NOT NULL,
    trip_id text NOT NULL,
    headsign text NOT NULL,
    direction_id text NOT NULL,
    stop_sequence integer NOT NULL,
    scheduled_departure timestamptz NOT NULL,
    predicted_departure timestamptz NOT NULL,
    delay_seconds integer NOT NULL,
    delay_category text NOT NULL,
    created_at timestamptz NOT NULL,
    duplicate_key text NOT NULL,
    CONSTRAINT delay_observations_collection_run_id_fkey
        FOREIGN KEY (collection_run_id) REFERENCES collection_runs (id),
    CONSTRAINT delay_observations_route_id_fkey
        FOREIGN KEY (route_id) REFERENCES routes (id),
    CONSTRAINT delay_observations_stop_id_fkey
        FOREIGN KEY (stop_id) REFERENCES stops (id),
    CONSTRAINT delay_observations_duplicate_key_key
        UNIQUE (duplicate_key)
);

COMMIT;
