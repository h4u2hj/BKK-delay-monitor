-- Verify the PostgreSQL source before building Data Fusion pipelines.
-- Run this against the existing PostgreSQL database.
-- Expected schema for this app: transit_data.

SET search_path TO transit_data, public;

-- 1) Confirm the source tables and columns that will feed BigQuery.
SELECT
    table_name,
    ordinal_position,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'transit_data'
  AND table_name IN (
      'routes',
      'stops',
      'collection_runs',
      'delay_observations',
      'route_stops'
  )
ORDER BY table_name, ordinal_position;

-- 2) Check source row counts.
SELECT 'routes' AS table_name, COUNT(*) AS row_count FROM routes
UNION ALL
SELECT 'stops' AS table_name, COUNT(*) AS row_count FROM stops
UNION ALL
SELECT 'collection_runs' AS table_name, COUNT(*) AS row_count FROM collection_runs
UNION ALL
SELECT 'delay_observations' AS table_name, COUNT(*) AS row_count FROM delay_observations
ORDER BY table_name;

-- 3) Check usable time range and delay distribution.
SELECT
    COUNT(*) AS observations,
    MIN(created_at) AS first_observed_at,
    MAX(created_at) AS last_observed_at,
    MIN(delay_seconds) AS min_delay_seconds,
    MAX(delay_seconds) AS max_delay_seconds,
    ROUND(AVG(delay_seconds)::numeric, 2) AS avg_delay_seconds
FROM delay_observations;

-- 4) Check mandatory fields for the planned warehouse fact table.
SELECT
    COUNT(*) FILTER (WHERE id IS NULL) AS missing_id,
    COUNT(*) FILTER (WHERE route_id IS NULL OR route_id = '') AS missing_route_id,
    COUNT(*) FILTER (WHERE stop_id IS NULL OR stop_id = '') AS missing_stop_id,
    COUNT(*) FILTER (WHERE direction_id IS NULL OR direction_id = '') AS missing_direction_id,
    COUNT(*) FILTER (WHERE created_at IS NULL) AS missing_created_at,
    COUNT(*) FILTER (WHERE scheduled_departure IS NULL) AS missing_scheduled_departure,
    COUNT(*) FILTER (WHERE predicted_departure IS NULL) AS missing_predicted_departure,
    COUNT(*) FILTER (WHERE delay_seconds IS NULL) AS missing_delay_seconds,
    COUNT(*) FILTER (WHERE delay_seconds < 0) AS negative_delay_seconds
FROM delay_observations;

-- 5) Check dimension join coverage.
SELECT
    COUNT(*) FILTER (WHERE r.id IS NULL) AS observations_without_route,
    COUNT(*) FILTER (WHERE s.id IS NULL) AS observations_without_stop
FROM delay_observations AS o
LEFT JOIN routes AS r ON r.id = o.route_id
LEFT JOIN stops AS s ON s.id = o.stop_id;

-- 6) Preview records for the project documentation and Data Fusion source setup.
SELECT
    id AS observation_id,
    route_id,
    stop_id,
    direction_id,
    headsign,
    stop_sequence,
    created_at AS observed_at,
    scheduled_departure,
    predicted_departure,
    delay_seconds,
    delay_category
FROM delay_observations
ORDER BY created_at DESC
LIMIT 20;
