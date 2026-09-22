-- name: kpi_summary
SELECT
  ROUND(AVG(delay_minutes), 2) AS avg_delay_minutes,
  ROUND(MAX(delay_minutes), 2) AS max_delay_minutes,
  SUM(observation_count) AS observation_count,
  SAFE_DIVIDE(SUM(delayed_count), SUM(observation_count)) AS delayed_ratio,
  SUM(significant_or_severe_count) AS significant_or_severe_count
FROM `{dashboard_view}`;

-- name: stop_delay_ranking
SELECT
  stop_name,
  COALESCE(NULLIF(headsign, ''), 'unknown') AS headsign,
  ROUND(AVG(delay_minutes), 2) AS avg_delay_minutes,
  SUM(significant_or_severe_count) AS significant_or_severe_count,
  SUM(observation_count) AS observation_count
FROM `{dashboard_view}`
GROUP BY stop_name, headsign
ORDER BY avg_delay_minutes DESC, significant_or_severe_count DESC
LIMIT 15;

-- name: daily_delay_trend
SELECT
  calendar_date,
  route_number,
  ROUND(AVG(delay_minutes), 2) AS avg_delay_minutes,
  SUM(observation_count) AS observation_count
FROM `{dashboard_view}`
GROUP BY calendar_date, route_number
ORDER BY calendar_date, route_number;

-- name: hourly_delay_trend
WITH hours AS (
  SELECT observed_hour
  FROM UNNEST(GENERATE_ARRAY(0, 23)) AS observed_hour
),
aggregates AS (
  SELECT
    observed_hour,
    ROUND(AVG(delay_minutes), 2) AS avg_delay_minutes,
    SUM(observation_count) AS observation_count
  FROM `{dashboard_view}`
  GROUP BY observed_hour
)
SELECT
  hours.observed_hour,
  COALESCE(aggregates.avg_delay_minutes, 0) AS avg_delay_minutes,
  COALESCE(aggregates.observation_count, 0) AS observation_count
FROM hours
LEFT JOIN aggregates
  ON aggregates.observed_hour = hours.observed_hour
ORDER BY hours.observed_hour;

-- name: delay_category_breakdown
SELECT
  delay_category,
  SUM(observation_count) AS observation_count
FROM `{dashboard_view}`
GROUP BY delay_category
ORDER BY
  CASE delay_category
    WHEN 'on time' THEN 1
    WHEN 'minor delay' THEN 2
    WHEN 'significant delay' THEN 3
    WHEN 'severe delay' THEN 4
    ELSE 5
  END;

-- name: time_period_delay_matrix
SELECT
  route_number,
  time_period,
  ROUND(AVG(delay_minutes), 2) AS avg_delay_minutes,
  SUM(observation_count) AS observation_count
FROM `{dashboard_view}`
GROUP BY route_number, time_period
ORDER BY route_number, time_period;
