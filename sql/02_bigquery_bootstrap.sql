-- Create the BigQuery datasets used by the warehouse project.
-- Replace PROJECT_ID with your Google Cloud project ID before running.

CREATE SCHEMA IF NOT EXISTS `PROJECT_ID.bkk_raw`
OPTIONS(location = 'EU');

CREATE SCHEMA IF NOT EXISTS `PROJECT_ID.bkk_dw`
OPTIONS(location = 'EU');
