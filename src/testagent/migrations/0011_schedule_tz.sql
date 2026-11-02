-- Schedules carry their IANA timezone (default Asia/Shanghai from config).
-- Cron schedules created before this migration were evaluated in UTC: keep that meaning
-- explicitly so nothing silently shifts by 8 hours; they can be switched in the task page.
UPDATE test_task SET schedule = schedule || '{"tz": "UTC"}'::jsonb
 WHERE schedule IS NOT NULL AND schedule->>'type' = 'cron' AND NOT (schedule ? 'tz');
UPDATE test_task SET schedule = schedule || '{"tz": "Asia/Shanghai"}'::jsonb
 WHERE schedule IS NOT NULL AND schedule->>'type' = 'once' AND NOT (schedule ? 'tz');
