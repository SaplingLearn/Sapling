"""Hermetic test for the #620 `flags` oracle judge."""

from e2e_oracles import gather


def test_flags_oracle_flags_invalid_variants():
    rows_flags = [{"key": "learning_loop", "default_variant": "banana", "rollout_variant": None}]
    rows_targets = [{"flag_key": "decision_router", "target_type": "user",
                     "target_id": "u1", "variant": "on"}]
    findings = gather.flag_findings(rows_flags, rows_targets)
    assert {f.evidence["key"] for f in findings} == {"learning_loop", "decision_router"}
    assert gather.flag_findings(
        [{"key": "learning_loop", "default_variant": "on", "rollout_variant": None}], []) == []
