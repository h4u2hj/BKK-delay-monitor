-- Run in BigQuery Studio after the initial raw loads; replace PROJECT_ID.
-- Target tables are preserved on rerun. dim_date is rebuilt from the full raw history.
-- Data Fusion populates the route, stop, and fact tables.

CREATE OR REPLACE TABLE `PROJECT_ID.bkk_dw.dim_date` AS
WITH bounds AS (
    SELECT
        DATE(MIN(created_at), 'Europe/Budapest') AS start_date,
        DATE(MAX(created_at), 'Europe/Budapest') AS end_date
    FROM `PROJECT_ID.bkk_raw.delay_observations`
)
SELECT
    CAST(FORMAT_DATE('%Y%m%d', calendar_date) AS INT64) AS date_key,
    calendar_date,
    EXTRACT(YEAR FROM calendar_date) AS year,
    EXTRACT(MONTH FROM calendar_date) AS month,
    FORMAT_DATE('%B', calendar_date) AS month_name,
    EXTRACT(DAYOFWEEK FROM calendar_date) AS day_of_week_number,
    CASE
        WHEN EXTRACT(DAYOFWEEK FROM calendar_date) IN (1, 7) THEN 'weekend'
        ELSE 'weekday'
    END AS day_type
FROM bounds,
UNNEST(GENERATE_DATE_ARRAY(start_date, end_date)) AS calendar_date;

CREATE TABLE IF NOT EXISTS `PROJECT_ID.bkk_dw.dim_route`
(
    route_key STRING,
    source_route_id STRING,
    route_number STRING,
    route_name STRING,
    route_type STRING
);

CREATE TABLE IF NOT EXISTS `PROJECT_ID.bkk_dw.dim_stop`
(
    stop_key STRING,
    source_stop_id STRING,
    stop_name STRING,
    lat FLOAT64,
    lon FLOAT64
);

CREATE TABLE IF NOT EXISTS `PROJECT_ID.bkk_dw.fact_delay_observation`
(
    source_observation_id STRING,
    date_key INT64,
    route_key STRING,
    stop_key STRING,
    collection_run_id STRING,
    trip_id STRING,
    headsign STRING,
    direction_id STRING,
    stop_sequence INT64,
    observed_at TIMESTAMP,
    scheduled_departure TIMESTAMP,
    predicted_departure TIMESTAMP,
    delay_seconds INT64,
    delay_minutes FLOAT64,
    delay_category STRING,
    source_delay_category STRING,
    time_period STRING,
    observation_count INT64
)
PARTITION BY DATE(observed_at)
CLUSTER BY route_key, stop_key;
