-- name: predicted_delay_by_station
WITH prediction_context AS (
  SELECT CURRENT_DATETIME('Europe/Budapest') AS prediction_time
),
station_candidates AS (
  SELECT
    observation.stop_id,
    stop.name AS stop_name,
    CASE
      WHEN LOWER(COALESCE(NULLIF(observation.headsign, ''), 'unknown')) IN (
        'ujbuda-kozpont m',
        'újbuda-központ m',
        'moricz zsigmond korter m',
        'móricz zsigmond körtér m'
      )
        THEN 'Újbuda-központ M / Móricz Zsigmond körtér M'
      ELSE COALESCE(NULLIF(observation.headsign, ''), 'unknown')
    END AS headsign,
    context.prediction_time,
    EXTRACT(HOUR FROM context.prediction_time) AS hour_of_day,
    SIN(
      2 * ACOS(-1) * EXTRACT(HOUR FROM context.prediction_time) / 24
    ) AS hour_sin,
    COS(
      2 * ACOS(-1) * EXTRACT(HOUR FROM context.prediction_time) / 24
    ) AS hour_cos
  FROM `{delay_observations_table}` AS observation
  CROSS JOIN prediction_context AS context
  LEFT JOIN `{stops_table}` AS stop
    ON stop.id = observation.stop_id
  WHERE observation.route_id IN ('BKK_3040', 'BKK_3060')
    AND observation.stop_id IS NOT NULL
),
station_inputs AS (
  SELECT
    stop_id,
    COALESCE(ANY_VALUE(stop_name), stop_id) AS stop_name,
    headsign,
    prediction_time,
    hour_of_day,
    hour_sin,
    hour_cos
  FROM station_candidates
  GROUP BY
    stop_id,
    headsign,
    prediction_time,
    hour_of_day,
    hour_sin,
    hour_cos
),
predictions AS (
  SELECT *
  FROM ML.PREDICT(
    MODEL `{delay_prediction_model}`,
    (
      SELECT
        stop_id,
        headsign,
        hour_of_day,
        hour_sin,
        hour_cos
      FROM station_inputs
    )
  )
)
SELECT
  station_inputs.stop_id,
  station_inputs.stop_name,
  station_inputs.headsign,
  station_inputs.prediction_time,
  predictions.predicted_delay_seconds
FROM predictions
JOIN station_inputs
  USING (stop_id, headsign, hour_of_day, hour_sin, hour_cos)
ORDER BY stop_name, headsign;

-- name: average_delay_by_stop
SELECT
  observation.stop_id,
  COALESCE(ANY_VALUE(stop.name), observation.stop_id) AS stop_name,
  CASE
    WHEN LOWER(COALESCE(NULLIF(observation.headsign, ''), 'unknown')) IN (
      'ujbuda-kozpont m',
      'újbuda-központ m',
      'moricz zsigmond korter m',
      'móricz zsigmond körtér m'
    )
      THEN 'Újbuda-központ M / Móricz Zsigmond körtér M'
    ELSE COALESCE(NULLIF(observation.headsign, ''), 'unknown')
  END AS headsign,
  COUNT(*) AS observation_count,
  AVG(observation.delay_seconds) AS average_delay_seconds
FROM `{delay_observations_table}` AS observation
LEFT JOIN `{stops_table}` AS stop
  ON stop.id = observation.stop_id
WHERE observation.route_id IN ('BKK_3040', 'BKK_3060')
GROUP BY observation.stop_id, headsign
ORDER BY average_delay_seconds DESC, observation_count DESC;

-- name: delayed_ratio_by_time_period
SELECT
  DATETIME_TRUNC(scheduled_departure, HOUR) AS period_start,
  COUNT(*) AS observation_count,
  COUNTIF(delay_seconds > 60) AS delayed_count,
  SAFE_DIVIDE(COUNTIF(delay_seconds > 60), COUNT(*)) AS delayed_ratio,
  AVG(delay_seconds) AS average_delay_seconds
FROM `{delay_observations_table}`
WHERE route_id IN ('BKK_3040', 'BKK_3060')
  AND scheduled_departure >= DATETIME_SUB(
    DATETIME(CURRENT_TIMESTAMP(), 'Europe/Budapest'),
    INTERVAL @hours HOUR
  )
GROUP BY period_start
ORDER BY period_start;

-- name: most_problematic_stops
SELECT
  observation.stop_id,
  COALESCE(ANY_VALUE(stop.name), observation.stop_id) AS stop_name,
  CASE
    WHEN LOWER(COALESCE(NULLIF(observation.headsign, ''), 'unknown')) IN (
      'ujbuda-kozpont m',
      'újbuda-központ m',
      'moricz zsigmond korter m',
      'móricz zsigmond körtér m'
    )
      THEN 'Újbuda-központ M / Móricz Zsigmond körtér M'
    ELSE COALESCE(NULLIF(observation.headsign, ''), 'unknown')
  END AS headsign,
  COUNT(*) AS observation_count,
  AVG(observation.delay_seconds) AS average_delay_seconds,
  SAFE_DIVIDE(
    COUNTIF(observation.delay_seconds > 60),
    COUNT(*)
  ) AS delayed_ratio,
  COUNTIF(observation.delay_category = 'major_delay') AS major_delay_count
FROM `{delay_observations_table}` AS observation
LEFT JOIN `{stops_table}` AS stop
  ON stop.id = observation.stop_id
WHERE observation.route_id IN ('BKK_3040', 'BKK_3060')
GROUP BY observation.stop_id, headsign
ORDER BY delayed_ratio DESC, average_delay_seconds DESC;
