"""Eval datasets for Sapling agents.

Three modes via SAPLING_EVAL_MODE env var:
- replay (default): hit cassettes only; CI uses this.
- record: hit live Gemini, write cassettes.
- live: hit live Gemini, no recording.

Recording workflow:
  cd backend
  SAPLING_EVAL_MODE=record python tests/evals/document_classification.py
  git add tests/evals/cassettes
  git commit -m "evals: refresh classifier cassettes"

Adding a new case: add it to CASES, then re-record (or commit alongside
a hand-written cassette under cassettes/<dataset>/<safe_name>.json).
"""
