-- Creates the normalized analytics table from Firestore BigQuery CREATE events.
-- Firestore timestamp seconds are converted to UTC+2 local wall time and stored
-- as DATETIME values under the normal application column names.
-- Edit the project or dataset name below if your Firestore extension tables live
-- somewhere other than bkktransitapp.bkk_analytics.

CREATE TEMP FUNCTION firestore_timestamp(ts_json STRING)
RETURNS TIMESTAMP
AS (
  IF(
    ts_json IS NULL,
    NULL,
    TIMESTAMP_MICROS(
      SAFE_CAST(JSON_VALUE(ts_json, '$._seconds') AS INT64) * 1000000
      + DIV(
        IFNULL(SAFE_CAST(JSON_VALUE(ts_json, '$._nanoseconds') AS INT64), 0),
        1000
      )
    )
  )
);

CREATE TEMP FUNCTION utc_plus_2_datetime(ts TIMESTAMP)
RETURNS DATETIME
AS (
  IF(ts IS NULL, NULL, DATETIME(TIMESTAMP_ADD(ts, INTERVAL 2 HOUR)))
);

CREATE OR REPLACE TABLE `bkktransitapp.bkk_analytics.delay_observations`
(
  id STRING,
  collection_run_id STRING,
  route_id STRING,
  stop_id STRING,
  trip_id STRING,
  headsign STRING,
  direction_id STRING,
  stop_sequence INT64,
  scheduled_departure DATETIME,
  predicted_departure DATETIME,
  delay_seconds INT64,
  delay_category STRING,
  created_at DATETIME
)
PARTITION BY DATE(created_at)
CLUSTER BY route_id, stop_id;

INSERT INTO `bkktransitapp.bkk_analytics.delay_observations`
(
  id,
  collection_run_id,
  route_id,
  stop_id,
  trip_id,
  headsign,
  direction_id,
  stop_sequence,
  scheduled_departure,
  predicted_departure,
  delay_seconds,
  delay_category,
  created_at
)
WITH create_events AS (
  SELECT
    timestamp AS changelog_timestamp,
    data,
    document_id
  FROM `bkktransitapp.bkk_analytics.delay_observations_raw_changelog`
  WHERE document_id IS NOT NULL
    AND UPPER(operation) = 'CREATE'
    AND data IS NOT NULL
),
parsed_events AS (
  SELECT
    changelog_timestamp,
    document_id,
    data,
    firestore_timestamp(JSON_QUERY(data, '$.scheduled_departure'))
      AS scheduled_departure_utc,
    firestore_timestamp(JSON_QUERY(data, '$.predicted_departure'))
      AS predicted_departure_utc,
    COALESCE(
      firestore_timestamp(JSON_QUERY(data, '$.created_at')),
      changelog_timestamp
    ) AS created_at_utc
  FROM create_events
)
SELECT
  COALESCE(JSON_VALUE(data, '$.id'), document_id) AS id,
  JSON_VALUE(data, '$.collection_run_id') AS collection_run_id,
  JSON_VALUE(data, '$.route_id') AS route_id,
  JSON_VALUE(data, '$.stop_id') AS stop_id,
  JSON_VALUE(data, '$.trip_id') AS trip_id,
  JSON_VALUE(data, '$.headsign') AS headsign,
  JSON_VALUE(data, '$.direction_id') AS direction_id,
  SAFE_CAST(JSON_VALUE(data, '$.stop_sequence') AS INT64) AS stop_sequence,
  utc_plus_2_datetime(scheduled_departure_utc) AS scheduled_departure,
  utc_plus_2_datetime(predicted_departure_utc) AS predicted_departure,
  SAFE_CAST(JSON_VALUE(data, '$.delay_seconds') AS INT64) AS delay_seconds,
  JSON_VALUE(data, '$.delay_category') AS delay_category,
  utc_plus_2_datetime(created_at_utc) AS created_at
FROM parsed_events;

SELECT
  COUNT(*) AS delay_observations_loaded,
  MIN(created_at) AS first_created_at,
  MAX(created_at) AS last_created_at
FROM `bkktransitapp.bkk_analytics.delay_observations`;
