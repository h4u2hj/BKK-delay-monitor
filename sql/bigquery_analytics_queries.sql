-- BigQuery analytics queries used by bkk_delays.bigquery_repository.
-- Table placeholders are rendered by Python after validating project, dataset,
-- and table identifiers. Keep BigQuery query parameters such as @hours in this
-- file; the repository binds their values with QueryJobConfig.

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
  SAFE_DIVIDE(COUNTIF(delay_seconds > 60), COUNT(*)) AS delayed_ratio
FROM `{delay_observations_table}`
WHERE route_id IN ('BKK_3040', 'BKK_3060')
  AND scheduled_departure >= DATETIME_SUB(
    DATETIME(TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)),
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
