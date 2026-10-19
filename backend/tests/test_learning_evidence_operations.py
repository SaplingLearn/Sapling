"""Only canonical route-owned identities can name a replayable evidence batch."""

import uuid

from pydantic import ValidationError
import pytest

from learning.evidence import Evidence


def test_legacy_evidence_does_not_acquire_a_synthetic_cross_request_identity():
    evidence = Evidence(node_id="node", channel="free_response", correct=False)
    assert evidence.operation_id is None


def test_canonical_claim_identity_survives_evidence_roundtrip():
    claim = str(uuid.uuid4())
    evidence = Evidence(node_id="node", channel="free_response", correct=False, operation_id=claim)
    assert Evidence.model_validate(evidence.model_dump()).operation_id == claim


@pytest.mark.parametrize("value", ["", "not-a-uuid", "00000000000040008000000000000000", "00000000-0000-4000-8000-00000000000A", True, 123])
def test_malformed_or_noncanonical_operation_is_rejected_before_writing(value):
    with pytest.raises(ValidationError):
        Evidence(node_id="node", channel="free_response", correct=False, operation_id=value)
