-- Ops alert emails (backend/services/spend_alerts.py) are ON by default:
-- an alert that has to be remembered to be switched on protects nobody.
-- Admins switch it off at /api/admin/flags (the kill switch);
-- SAPLING_FLAG_SPEND_ALERTS=off overrides it from the environment.
INSERT INTO feature_flags (key, default_variant) VALUES ('spend_alerts', 'on')
ON CONFLICT (key) DO NOTHING;
