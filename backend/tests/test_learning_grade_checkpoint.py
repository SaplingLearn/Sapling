"""Pure authenticated-envelope tests; no grader, database or provider calls."""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from learning.evidence import Evidence, PlanningPersistenceUnavailable
from learning import grade_checkpoint as cp
from services.encryption import decrypt, encrypt

NOW = datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc)
PRIVATE = "synthetic-private-learner-text"


def payload(kind="check", *, course_id="course"):
    operation = str(uuid4())
    evidence = Evidence(node_id="node", channel="free_response", correct=False,
        operation_id=operation, session_id="session", question_hash="question-hash", check_item_id="item",
        observed_at=NOW, planning_provenance={"check_item_id": "item", "difficulty": 2,
            "synthetic_idk": False, "previously_seen": False}).model_dump(mode="json")
    continuation = ({"graded": {"graded_at": NOW.timestamp(), "last_correct": False,
        "last_verdict": "not_yet", "max_rung": 0, "assisted": False, "node_id": "node",
        "channel": "free_response", "confidence": None, "grader_backend": None,
        "fsrs_rating": 1, "p_before": .5, "feedback_given": False},
        "correct": False, "genuine": True, "diagnosis": None,
        "rendered": "Review the base case.", "answer": {"question_hash": "question-hash",
            "answer_text": PRIVATE, "selected_option": None, "reason": None, "idk": False},
        "verdict": "not_yet", "refused": False} if kind == "check" else {
        "observation": {"node_id": "node", "question_hash": "question-hash", "difficulty": 2,
                        "channel": "free_response", "correct": False, "idk": False, "independent": True,
                        "max_rung": 0, "same_session_recheck": False, "synthetic_idk": False},
        "correct": False, "check_item_id": "item"})
    return {"kind": kind, "operation_id": operation, "user_id": "owner", "session_id": "session",
            "course_id": course_id, "question_hash": "question-hash", "goal_version": 2,
            "evidence": [evidence], "continuation": continuation}


def bindings(value):
    return {key: value[key] for key in ("kind", "operation_id", "user_id", "session_id", "course_id", "question_hash")}


@pytest.mark.parametrize("kind", ["check", "probe"])
@pytest.mark.parametrize("course_id", [None, "course"])
def test_encrypted_roundtrip_binds_full_metadata_and_exact_evidence(kind, course_id):
    data = payload(kind, course_id=course_id)
    checkpoint = cp.GradeCheckpoint.model_validate(data)
    sealed = cp.seal(checkpoint)
    recovered = cp.open_checkpoint(sealed, **bindings(data))
    assert recovered == checkpoint
    assert recovered.evidence[0]["observed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert PRIVATE not in sealed and "question-hash" not in sealed
    assert recovered.operation_id == data["operation_id"]


def test_metadata_serialization_is_deterministic_but_encryption_is_randomized():
    checkpoint = cp.GradeCheckpoint.model_validate(payload())
    first, second = cp.seal(checkpoint), cp.seal(checkpoint)
    assert first != second
    expected = json.dumps(checkpoint.model_dump(mode="json"), sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    assert decrypt(first) == decrypt(second) == expected
    assert cp.open_checkpoint(first, **bindings(checkpoint.model_dump())) == checkpoint


@pytest.mark.parametrize("key,value", [("kind", "probe"), ("operation_id", str(uuid4())),
    ("user_id", "other"), ("session_id", "other-session"), ("course_id", "other-course"),
    ("course_id", None), ("question_hash", "other-question")])
def test_valid_ciphertext_cannot_be_opened_for_different_identity(key, value):
    data = payload()
    expected = {**bindings(data), key: value}
    sealed = cp.seal(cp.GradeCheckpoint.model_validate(data))
    with pytest.raises(PlanningPersistenceUnavailable, match="^Saved grade recovery unavailable$"):
        cp.open_checkpoint(sealed, **expected)


@pytest.mark.parametrize("key,value", [("operation_id", str(uuid4())), ("session_id", "other-session"),
    ("question_hash", "other-question"), ("observed_at", None),
    ("observed_at", "2026-10-19T15:30:00")])
def test_evidence_must_bind_operation_session_question_and_aware_observation(key, value):
    data = payload()
    data["evidence"][0][key] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_every_evidence_row_is_bound_not_only_the_first():
    data = payload()
    data["evidence"].append({**data["evidence"][0], "node_id": "second", "operation_id": str(uuid4())})
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_empty_evidence_cannot_create_a_recoverable_grade():
    data = payload()
    data["evidence"] = []
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_mixed_observation_times_fail_before_sealing():
    data = payload()
    data["evidence"].append({**data["evidence"][0], "node_id": "second",
                             "observed_at": (NOW + timedelta(seconds=1)).isoformat()})
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_equivalent_aware_times_are_canonical_utc_in_each_evidence():
    data = payload()
    data["evidence"].append({**data["evidence"][0], "node_id": "second",
                             "observed_at": "2026-10-19T11:30:00-04:00"})
    checkpoint = cp.GradeCheckpoint.model_validate(data)
    assert len({row["observed_at"] for row in checkpoint.evidence}) == 1
    assert Evidence.model_validate(checkpoint.evidence[0]).observed_at == NOW


@pytest.mark.parametrize("value", ["", "not-a-uuid", str(uuid4()).upper(), True, 7])
def test_noncanonical_operation_identity_is_rejected(value):
    data = payload()
    data["operation_id"] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("value", [-1, True, "2", 2.5])
def test_goal_version_requires_nonnegative_strict_integer(value):
    data = payload()
    data["goal_version"] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("kind", ["check", "probe"])
@pytest.mark.parametrize("change", ["missing", "extra", "other_kind"])
def test_continuation_has_only_the_kind_specific_code_fields(kind, change):
    data = payload(kind)
    if change == "missing":
        data["continuation"].pop("correct")
    elif change == "extra":
        data["continuation"]["reference_answer"] = "forbidden-reference"
    else:
        data["continuation"] = payload("probe" if kind == "check" else "check")["continuation"]
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_ignored_raw_evidence_keys_cannot_serialize_reference_or_rubric():
    data = payload()
    data["evidence"][0].update(reference_answer="forbidden-reference", rubric="forbidden-rubric",
                                learner_answer="unapproved-extra-copy")
    checkpoint = cp.GradeCheckpoint.model_validate(data)
    sealed = cp.seal(checkpoint)
    decoded = json.loads(decrypt(sealed))
    assert set(decoded["evidence"][0]) == set(Evidence.model_fields)
    assert "forbidden-reference" not in decrypt(sealed)
    assert "forbidden-rubric" not in decrypt(sealed)
    assert "unapproved-extra-copy" not in decrypt(sealed)
    assert decoded["continuation"]["answer"]["answer_text"] == PRIVATE


@pytest.mark.parametrize("part", ["nonce", "ciphertext", "tag"])
def test_mutating_any_authenticated_ciphertext_component_rejects_recovery(part):
    data = payload()
    sealed = cp.seal(cp.GradeCheckpoint.model_validate(data))
    raw = bytearray(base64.b64decode(sealed))
    index = {"nonce": 0, "ciphertext": 12, "tag": -1}[part]
    raw[index] ^= 1
    altered = base64.b64encode(raw).decode()
    with pytest.raises(PlanningPersistenceUnavailable):
        cp.open_checkpoint(altered, **bindings(data))


@pytest.mark.parametrize("value", [None, {}, [], 7, b"ciphertext", "", "not encrypted"])
def test_missing_or_non_encrypted_input_has_no_plaintext_fallback(value):
    data = payload()
    with pytest.raises(PlanningPersistenceUnavailable):
        cp.open_checkpoint(value, **bindings(data))


def test_json_plaintext_is_rejected_even_if_it_is_a_valid_checkpoint():
    data = payload()
    plaintext = cp.GradeCheckpoint.model_validate(data).model_dump_json()
    with pytest.raises(PlanningPersistenceUnavailable):
        cp.open_checkpoint(plaintext, **bindings(data))


def test_authenticated_invalid_payload_and_unknown_top_level_keys_are_rejected():
    data = payload()
    for change in ({"version": 2}, {"reference_answer": PRIVATE}, {"kind": "unknown"}, {"evidence": []}):
        invalid = {**deepcopy(data), **change}
        sealed = encrypt(json.dumps(invalid))
        with pytest.raises(PlanningPersistenceUnavailable):
            cp.open_checkpoint(sealed, **bindings(data))


def test_recovery_error_and_logs_do_not_expose_ciphertext_or_validation_payload(caplog):
    data = payload()
    data["evidence"][0]["observed_at"] = PRIVATE
    sealed = encrypt(json.dumps(data))
    with pytest.raises(PlanningPersistenceUnavailable) as error:
        cp.open_checkpoint(sealed, **bindings(data))
    assert str(error.value) == "Saved grade recovery unavailable"
    assert error.value.__cause__ is None and error.value.__suppress_context__ is True
    assert PRIVATE not in str(error.value) and sealed not in str(error.value)
    assert PRIVATE not in caplog.text and sealed not in caplog.text


def test_each_open_returns_independent_objects():
    data = payload()
    sealed = cp.seal(cp.GradeCheckpoint.model_validate(data))
    first = cp.open_checkpoint(sealed, **bindings(data))
    first.evidence[0]["node_id"] = "changed"
    first.continuation["answer"]["answer_text"] = "changed"
    second = cp.open_checkpoint(sealed, **bindings(data))
    assert second.evidence[0]["node_id"] == "node" and second.continuation["answer"]["answer_text"] == PRIVATE


@pytest.mark.parametrize("field,value", [("graded", True), ("answer", "learner text"),
    ("correct", "false"), ("genuine", 1), ("refused", "false"), ("verdict", "gap"),
    ("diagnosis", "not metadata"), ("rendered", None)])
def test_check_continuation_rejects_wrong_value_types(field, value):
    data = payload()
    data["continuation"][field] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("field,value", [("node_id", "other-node"), ("last_correct", True),
    ("last_verdict", "correct"), ("channel", "mc"), ("max_rung", 2), ("assisted", True),
    ("confidence", .9), ("grader_backend", "gemini"), ("graded_at", NOW.timestamp() + 1),
    ("p_before", float("nan")), ("fsrs_rating", True), ("reference_answer", "forbidden")])
def test_check_graded_metadata_is_typed_and_bound_to_evidence(field, value):
    data = payload()
    data["continuation"]["graded"][field] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("field,value", [("question_hash", "other-question"), ("idk", True),
    ("idk", "false"), ("reason", {}), ("reference_answer", "forbidden")])
def test_check_answer_has_typed_allowed_fields_and_exact_question_binding(field, value):
    data = payload()
    data["continuation"]["answer"][field] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("field,value", [("node_id", "other-node"), ("question_hash", "other"),
    ("correct", True), ("idk", True), ("channel", "mc"), ("max_rung", 1),
    ("same_session_recheck", True), ("independent", "true"), ("difficulty", True),
    ("reference_answer", "forbidden")])
def test_probe_observation_has_typed_fields_and_exact_evidence_binding(field, value):
    data = payload("probe")
    data["continuation"]["observation"][field] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("field,value", [("correct", True), ("check_item_id", "other-item"),
    ("correct", 0), ("observation", [])])
def test_probe_top_level_continuation_is_typed_and_bound(field, value):
    data = payload("probe")
    data["continuation"][field] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_seal_revalidates_mutated_model_and_has_no_sensitive_exception_payload():
    checkpoint = cp.GradeCheckpoint.model_validate(payload())
    checkpoint.continuation["answer"]["reference_answer"] = PRIVATE
    with pytest.raises(PlanningPersistenceUnavailable) as error:
        cp.seal(checkpoint)
    assert str(error.value) == "Saved grade checkpoint unavailable"
    assert PRIVATE not in str(error.value) and error.value.__cause__ is None


@pytest.mark.parametrize("kind", ["check", "probe"])
@pytest.mark.parametrize("correct,idk,rung,recheck,synthetic", [
    (True, False, 0, False, False), (False, True, 0, False, False),
    (True, False, 2, False, False), (True, False, 0, True, False),
    (False, True, 0, False, True),
])
def test_actual_valid_outcomes_help_and_rechecks_roundtrip(kind, correct, idk, rung, recheck, synthetic):
    from learning.evidence import planning_observation
    data = payload(kind)
    raw = data["evidence"][0]
    raw.update(correct=correct, idk=idk, max_rung=rung, same_session_recheck=recheck)
    raw["planning_provenance"]["synthetic_idk"] = synthetic
    ev = Evidence.model_validate(raw)
    data["evidence"][0] = ev.model_dump(mode="json")
    metadata = planning_observation(ev)
    continuation = data["continuation"]
    continuation["correct"] = correct
    if kind == "probe":
        continuation["observation"] = {key: metadata[key] for key in continuation["observation"]}
    else:
        verdict = "idk" if idk else "correct" if correct else "not_yet"
        continuation.update(verdict=verdict, genuine=not idk, refused=synthetic)
        continuation["answer"]["idk"] = idk
        continuation["graded"].update(last_correct=correct, last_verdict=verdict,
            max_rung=rung, assisted=ev.assisted)
        continuation["graded"]["goal_observation"] = {key: metadata[key] for key in (
            "node_id", "question_hash", "difficulty", "channel", "correct", "idk", "max_rung",
            "same_session_recheck", "synthetic_idk", "independent", "previously_seen",
        )}
    checkpoint = cp.GradeCheckpoint.model_validate(data)
    assert cp.open_checkpoint(cp.seal(checkpoint), **bindings(data)) == checkpoint


def rich_diagnosis():
    return {"attempt": {"question_hash": "question-hash", "node_id": "node", "correct": False,
        "wrong_key": "wrong_rule", "confidence": .9, "difficulty": 2, "idk": False,
        "isomorph_of": None, "released": True, "after_release": False},
        "confront": {"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "item"},
        "cleared": None,
        "record": {"node_id": "node", "wrong_key": "wrong_rule", "check_item_id": "item"}}


def test_actual_rich_diagnosis_is_canonical_metadata_without_reference_fields():
    data = payload()
    data["continuation"]["diagnosis"] = rich_diagnosis()
    checkpoint = cp.GradeCheckpoint.model_validate(data)
    recovered = cp.open_checkpoint(cp.seal(checkpoint), **bindings(data))
    assert recovered.continuation["diagnosis"] == rich_diagnosis()
    assert set(recovered.continuation["diagnosis"]) == {"attempt", "confront", "cleared", "record"}


@pytest.mark.parametrize("section,key,value", [("attempt", "question_hash", "other-question"),
    ("attempt", "node_id", "other-node"), ("attempt", "correct", True),
    ("attempt", "idk", True), ("attempt", "reference_answer", "forbidden"),
    ("confront", "node_id", "other-node"), ("record", "check_item_id", "other-item"),
    ("record", "rubric", "forbidden")])
def test_diagnosis_is_typed_bound_and_cannot_carry_reference_or_rubric(section, key, value):
    data = payload()
    diagnosis = rich_diagnosis()
    diagnosis[section][key] = value
    data["continuation"]["diagnosis"] = diagnosis
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


@pytest.mark.parametrize("value", [0, True, "false"])
def test_unmaterialized_feedback_requires_false_boolean(value):
    data = payload()
    data["continuation"]["graded"]["feedback_given"] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_nested_continuation_validation_error_hides_private_learner_input():
    data = payload()
    data["continuation"]["graded"] = True
    with pytest.raises(ValidationError) as error:
        cp.GradeCheckpoint.model_validate(data)
    assert PRIVATE not in str(error.value)
    assert "input_value" not in str(error.value)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_version_is_exact_integer_one(value):
    data = payload()
    data["version"] = value
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_refusal_flag_cannot_relabel_an_explicit_unknown_as_synthetic():
    data = payload()
    data["evidence"][0]["idk"] = True
    data["continuation"]["answer"]["idk"] = True
    data["continuation"].update(verdict="idk", genuine=False, refused=True)
    data["continuation"]["graded"]["last_verdict"] = "idk"
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_recovery_requires_one_unambiguous_primary_evidence():
    data = payload()
    data["evidence"].append(deepcopy(data["evidence"][0]))
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)


def test_probe_independence_cannot_upgrade_assisted_evidence():
    data = payload("probe")
    data["evidence"][0]["max_rung"] = 2
    data["continuation"]["observation"]["max_rung"] = 2
    assert data["continuation"]["observation"]["independent"] is True
    with pytest.raises(ValidationError):
        cp.GradeCheckpoint.model_validate(data)
