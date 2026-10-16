"""Hermetic test for the #620 `flags` oracle judge."""

from e2e_oracles import gather


def test_flags_oracle_flags_invalid_variants():
    rows_flags = [{"key": "hide_quiz", "default_variant": "banana", "rollout_variant": None}]
    rows_targets = [{"flag_key": "hide_tree", "target_type": "user",
                     "target_id": "u1", "variant": "banana"},
                    # A row for a flag no longer in the registry is not judged.
                    {"flag_key": "retired_flag", "target_type": "user",
                     "target_id": "u1", "variant": "banana"}]
    findings = gather.flag_findings(rows_flags, rows_targets)
    assert {f.evidence["key"] for f in findings} == {"hide_quiz", "hide_tree"}
    assert gather.flag_findings(
        [{"key": "hide_quiz", "default_variant": "on", "rollout_variant": None}], []) == []
