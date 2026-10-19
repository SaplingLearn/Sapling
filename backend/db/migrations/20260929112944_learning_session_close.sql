-- 20260929112944_learning_session_close.sql
-- Learning loop series PKG-09: the end-of-session close (model-written
-- summary, self-evaluation prompt, if-then plan), the phase the session
-- stopped in, and the session's learner brief. close_json is encrypted JSON
-- (services/encryption.py::encrypt_json); loop_brief is encrypted (A19)
-- (services/encryption.py::encrypt_if_present), built once per session.
-- Never filter or join on either. Spec §4 / §9 / §13 A19.
-- Existing table: RLS/grants unchanged (as 20260929050800_learning_loop_state_rev.sql);
-- both text columns hold ciphertext only, close_phase an enum value.
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS close_json text,          -- encrypted JSON {summary, self_eval, if_then, concepts:[{node_id, p_before, p_after}], misconceptions:[wrong_key]}
  ADD COLUMN IF NOT EXISTS close_phase text CHECK (close_phase IN ('probe','plan','teach','check','feedback','close')),
  ADD COLUMN IF NOT EXISTS loop_brief text;          -- encrypted learner brief, built once per session (A19)
