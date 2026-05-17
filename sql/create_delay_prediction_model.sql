-- BigQuery ML model for predicting BKK delay seconds by station and time of day.
-- Edit the project or dataset name below if your analytics dataset lives
-- somewhere other than bkktransitapp.bkk_analytics.
--
-- This trains from the normalized delay_observations table created by
-- create_delay_observations_from_changelog.sql. BigQuery ML automatically
-- one-hot encodes STRING columns such as stop_id and headsign.

CREATE OR REPLACE MODEL `bkktransitapp.bkk_analytics.delay_predictor_by_station_time`
OPTIONS (
  model_type = 'linear_reg',
  input_label_cols = ['delay_seconds'],
  data_split_method = 'AUTO_SPLIT',
  enable_global_explain = TRUE
) AS
WITH training_rows AS (
  SELECT
    stop_id,
    COALESCE(NULLIF(headsign, ''), 'unknown') AS headsign,
    EXTRACT(HOUR FROM scheduled_departure) AS hour_of_day,
    SIN(2 * ACOS(-1) * EXTRACT(HOUR FROM scheduled_departure) / 24) AS hour_sin,
    COS(2 * ACOS(-1) * EXTRACT(HOUR FROM scheduled_departure) / 24) AS hour_cos,
    delay_seconds
  FROM `bkktransitapp.bkk_analytics.delay_observations`
  WHERE route_id IN ('BKK_3040', 'BKK_3060')
    AND stop_id IS NOT NULL
    AND scheduled_departure IS NOT NULL
    AND delay_seconds IS NOT NULL
)
SELECT
  stop_id,
  headsign,
  hour_of_day,
  hour_sin,
  hour_cos,
  delay_seconds
FROM training_rows;

-- Evaluate model quality on BigQuery ML's generated evaluation split.
SELECT
  mean_absolute_error,
  mean_squared_error,
  mean_squared_log_error,
  median_absolute_error,
  r2_score,
  explained_variance
FROM ML.EVALUATE(
  MODEL `bkktransitapp.bkk_analytics.delay_predictor_by_station_time`
);

-- Example prediction: expected delay for each observed station/headsign at 08:00.
WITH station_inputs AS (
  SELECT DISTINCT
    stop_id,
    COALESCE(NULLIF(headsign, ''), 'unknown') AS headsign,
    8 AS hour_of_day,
    SIN(2 * ACOS(-1) * 8 / 24) AS hour_sin,
    COS(2 * ACOS(-1) * 8 / 24) AS hour_cos
  FROM `bkktransitapp.bkk_analytics.delay_observations`
  WHERE route_id IN ('BKK_3040', 'BKK_3060')
    AND stop_id IS NOT NULL
)
SELECT
  stop_id,
  headsign,
  hour_of_day,
  predicted_delay_seconds
FROM ML.PREDICT(
  MODEL `bkktransitapp.bkk_analytics.delay_predictor_by_station_time`,
  (SELECT * FROM station_inputs)
)
ORDER BY predicted_delay_seconds DESC;
