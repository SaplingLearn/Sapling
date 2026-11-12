"""Where one class's rows go on one account: the ids they are written under
and the rows of the account they hang off.

Every id is derived from the account and a key, so a re-run writes the same
rows. A concept or prerequisite the account already has (the rich seed's, or
the student's own) keeps the id it has.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

from db.local_study_data.spec import ClassData


def owner_prefix(owner_id: str) -> str:
    """Stable per-account prefix, so two local accounts never share rows."""
    return "study-" + hashlib.sha256(owner_id.encode()).hexdigest()[:10]


@dataclass(frozen=True)
class Enrolled:
    """What the account already has for a class."""

    enrollment_id: str
    offering_id: str
    #: Concept name to node id, for the concepts already on the tree.
    nodes: dict[str, str] = field(default_factory=dict)
    #: (source node id, target node id) to edge id, for its prerequisite edges.
    edges: dict[tuple[str, str], str] = field(default_factory=dict)


@dataclass(frozen=True)
class Placement:
    data: ClassData
    owner_id: str
    enrolled: Enrolled
    now: datetime

    @property
    def prefix(self) -> str:
        return f"{owner_prefix(self.owner_id)}-{self.data.key}"

    def node_id(self, concept_key: str) -> str:
        name = self.data.concept(concept_key).name
        return self.enrolled.nodes.get(name) or f"{self.prefix}-node-{concept_key}"

    def edge_id(self, source_key: str, target_key: str) -> str:
        pair = (self.node_id(source_key), self.node_id(target_key))
        return self.enrolled.edges.get(pair) or f"{self.prefix}-edge-{source_key}--{target_key}"

    def document_id(self, material_key: str) -> str:
        return f"{self.prefix}-doc-{material_key}"

    def assessment_id(self, assessment_key: str) -> str:
        return f"{self.prefix}-asg-{assessment_key}"

    def guide_id(self, guide_key: str) -> str:
        return f"{self.prefix}-guide-{guide_key}"
