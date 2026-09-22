-- Run after loading the warehouse; replace PROJECT_ID.
-- Shared reporting contract for Looker Studio and Flask statistics.

CREATE OR REPLACE VIEW `PROJECT_ID.bkk_dw.v_delay_dashboard` AS
SELECT
    d.calendar_date,
    d.year,
    d.month,
    d.month_name,
    d.day_of_week_number,
    d.day_type,
    r.route_number,
    r.route_name,
    r.route_type,
    s.stop_name,
    s.lat,
    s.lon,
    f.collection_run_id,
    f.trip_id,
    f.headsign,
    f.direction_id,
    f.stop_sequence,
    f.observed_at,
    DATETIME(f.observed_at, 'Europe/Budapest') AS observed_at_budapest,
    EXTRACT(HOUR FROM DATETIME(f.observed_at, 'Europe/Budapest')) AS observed_hour,
    f.scheduled_departure,
    f.predicted_departure,
    f.delay_seconds,
    f.delay_minutes,
    f.delay_category,
    f.source_delay_category,
    f.time_period,
    f.observation_count,
    CASE WHEN f.delay_seconds > 60 THEN 1 ELSE 0 END AS delayed_count,
    CASE
        WHEN f.delay_category IN ('significant delay', 'severe delay') THEN 1
        ELSE 0
    END AS significant_or_severe_count
FROM `PROJECT_ID.bkk_dw.fact_delay_observation` AS f
JOIN `PROJECT_ID.bkk_dw.dim_date` AS d
    ON d.date_key = f.date_key
JOIN `PROJECT_ID.bkk_dw.dim_route` AS r
    ON r.route_key = f.route_key
JOIN `PROJECT_ID.bkk_dw.dim_stop` AS s
    ON s.stop_key = f.stop_key
WHERE r.route_number IN ('4', '6');
