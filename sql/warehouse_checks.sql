-- Replace PROJECT_ID and run in BigQuery Studio after loading the warehouse.
-- Counts should match; every issue count below should be zero.

SELECT
  (SELECT COUNT(*) FROM `PROJECT_ID.bkk_raw.delay_observations`
   WHERE created_at IS NOT NULL AND delay_seconds IS NOT NULL
     AND delay_seconds >= 0) AS usable_raw_rows,
  (SELECT COUNT(*) FROM `PROJECT_ID.bkk_dw.fact_delay_observation`) AS fact_rows;

SELECT 'duplicate_fact_ids' AS issue, COUNT(*) AS issue_count
FROM (
  SELECT source_observation_id
  FROM `PROJECT_ID.bkk_dw.fact_delay_observation`
  GROUP BY source_observation_id HAVING COUNT(*) > 1
)
UNION ALL
SELECT 'duplicate_route_keys', COUNT(*)
FROM (
  SELECT route_key FROM `PROJECT_ID.bkk_dw.dim_route`
  GROUP BY route_key HAVING COUNT(*) > 1
)
UNION ALL
SELECT 'duplicate_stop_keys', COUNT(*)
FROM (
  SELECT stop_key FROM `PROJECT_ID.bkk_dw.dim_stop`
  GROUP BY stop_key HAVING COUNT(*) > 1
)
UNION ALL
SELECT 'duplicate_date_keys', COUNT(*)
FROM (
  SELECT date_key FROM `PROJECT_ID.bkk_dw.dim_date`
  GROUP BY date_key HAVING COUNT(*) > 1
);

SELECT
  COUNTIF(f.source_observation_id IS NULL) AS missing_observation_id,
  COUNTIF(d.date_key IS NULL) AS unresolved_date,
  COUNTIF(r.route_key IS NULL) AS unresolved_route,
  COUNTIF(s.stop_key IS NULL) AS unresolved_stop,
  COUNTIF(f.delay_seconds IS NULL OR f.delay_seconds < 0) AS invalid_delay,
  COUNTIF(f.observed_at IS NULL) AS missing_observed_at,
  COUNTIF(f.date_key != CAST(FORMAT_DATE(
    '%Y%m%d', DATE(f.observed_at, 'Europe/Budapest')) AS INT64))
    AS local_date_mismatch,
  COUNTIF(f.time_period IS NULL OR f.time_period != CASE
    WHEN EXTRACT(HOUR FROM DATETIME(f.observed_at, 'Europe/Budapest'))
      BETWEEN 6 AND 9 THEN 'morning peak'
    WHEN EXTRACT(HOUR FROM DATETIME(f.observed_at, 'Europe/Budapest'))
      BETWEEN 15 AND 18 THEN 'afternoon peak'
    ELSE 'other period'
  END) AS local_time_period_mismatch
FROM `PROJECT_ID.bkk_dw.fact_delay_observation` AS f
LEFT JOIN `PROJECT_ID.bkk_dw.dim_date` AS d USING (date_key)
LEFT JOIN `PROJECT_ID.bkk_dw.dim_route` AS r USING (route_key)
LEFT JOIN `PROJECT_ID.bkk_dw.dim_stop` AS s USING (stop_key);
