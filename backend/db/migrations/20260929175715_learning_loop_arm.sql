-- 20260929175715_learning_loop_arm.sql
-- Learning loop series PKG-14: within-student A/B arm label. NULL = no
-- experiment (every concept is variant A). learning/policy.py::variant_for
-- hashes (arm, user_id, node_id) so concepts are randomised WITHIN a student.
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;
