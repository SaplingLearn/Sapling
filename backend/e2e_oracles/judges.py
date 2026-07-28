"""Pure judges for the #400 E2E Chapter 2 oracle module.

No IO, no service imports at module level — every judge is a plain function
over already-gathered data (payload dict / DB rows / counts) that returns
`Finding`s. Task 3 wires these to SQL/HTTP gatherers; the ciphertext judge
takes `decrypt_fn` as a parameter so this module never imports
`services.encryption` (or any other service) itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from e2e_oracles.findings import Finding


def _duplicates(ids: list[str]) -> dict[str, int]:
    return {k: v for k, v in Counter(ids).items() if v > 1}


def graph_findings(
    payload: dict,
    db_nodes: list[dict],
    db_edges: list[dict],
    enrolled_course_ids: set[str],
) -> list[Finding]:
    """Check `GET /api/graph/{user_id}` payload shape against the DB (#355 oracle).

    `payload` is `{"nodes": [...], "edges": [...], "stats": {...}}`. Synthesized
    subject roots are `subject_root__{course_id}`; spokes are
    `subject_edge__subject_root__{course_id}__{node_id}`.
    """
    findings: list[Finding] = []

    payload_nodes = payload.get("nodes", [])
    payload_edges = payload.get("edges", [])
    payload_node_ids = [n["id"] for n in payload_nodes]
    payload_edge_ids = [e["id"] for e in payload_edges]

    node_id_dupes = _duplicates(payload_node_ids)
    if node_id_dupes:
        findings.append(
            Finding(
                oracle="graph",
                summary=f"Duplicate payload node ids: {sorted(node_id_dupes)}",
                evidence={"duplicates": node_id_dupes},
            )
        )

    edge_id_dupes = _duplicates(payload_edge_ids)
    if edge_id_dupes:
        findings.append(
            Finding(
                oracle="graph",
                summary=f"Duplicate payload edge ids: {sorted(edge_id_dupes)}",
                evidence={"duplicates": edge_id_dupes},
            )
        )

    db_node_ids = {n["id"] for n in db_nodes}
    expected_node_count = len(db_nodes) + len(enrolled_course_ids)
    payload_node_count = len(payload_nodes)
    if payload_node_count != expected_node_count:
        findings.append(
            Finding(
                oracle="graph",
                summary=(
                    f"Node count mismatch: payload={payload_node_count} "
                    f"expected={expected_node_count}"
                ),
                evidence={"payload": payload_node_count, "expected": expected_node_count},
            )
        )

    drawable = sum(
        1
        for e in db_edges
        if e["source_node_id"] in db_node_ids and e["target_node_id"] in db_node_ids
    )
    spokes = sum(1 for n in db_nodes if n.get("course_id") in enrolled_course_ids)
    expected_edge_count = drawable + spokes
    payload_edge_count = len(payload_edges)
    if payload_edge_count != expected_edge_count:
        findings.append(
            Finding(
                oracle="graph",
                summary=(
                    f"Edge count mismatch: payload={payload_edge_count} "
                    f"expected={expected_edge_count}"
                ),
                evidence={"payload": payload_edge_count, "expected": expected_edge_count},
            )
        )

    root_counts = Counter(n for n in payload_node_ids if n.startswith("subject_root__"))
    for course_id in sorted(enrolled_course_ids):
        root_id = f"subject_root__{course_id}"
        count = root_counts.get(root_id, 0)
        if count != 1:
            findings.append(
                Finding(
                    oracle="graph",
                    summary=f"{root_id} appears {count} times (expected 1)",
                    evidence={"root_id": root_id, "count": count},
                )
            )

    return findings


def ciphertext_findings(
    table: str,
    column: str,
    rows: list[tuple],
    decrypt_fn: Callable[[str], str],
) -> list[Finding]:
    """Flag rows in `table.column` that are not encrypted at rest.

    `rows` are `(pk, value)`. A value is "encrypted at rest" iff
    `decrypt_fn(value)` succeeds AND the plaintext differs from the raw value.
    Non-str values are findings too. Evidence truncates the raw value to 32
    chars so a possibly-plaintext value is never fully leaked into reports.
    """
    findings: list[Finding] = []
    for pk, value in rows:
        if not isinstance(value, str):
            findings.append(
                Finding(
                    oracle="ciphertext",
                    summary=f"{table}.{column} non-string value at rest (pk={pk})",
                    evidence={"pk": pk, "value_prefix": str(value)[:32]},
                )
            )
            continue
        try:
            plain = decrypt_fn(value)
        except Exception:
            findings.append(
                Finding(
                    oracle="ciphertext",
                    summary=f"{table}.{column} not encrypted at rest (pk={pk})",
                    evidence={"pk": pk, "value_prefix": value[:32]},
                )
            )
            continue
        if plain == value:
            findings.append(
                Finding(
                    oracle="ciphertext",
                    summary=f"{table}.{column} not encrypted at rest (pk={pk})",
                    evidence={"pk": pk, "value_prefix": value[:32]},
                )
            )
    return findings


def count_findings(name: str, api_count: int, db_count: int) -> list[Finding]:
    """Flag a mismatch between an API-reported count and the DB's own count."""
    if api_count == db_count:
        return []
    return [
        Finding(
            oracle="counts",
            summary=f"{name} count mismatch: api={api_count} db={db_count}",
            evidence={"api_count": api_count, "db_count": db_count},
        )
    ]


def orphan_findings(check_name: str, orphan_ids: list) -> list[Finding]:
    """Flag rows whose foreign key points nowhere, e.g. `graph_edges→graph_nodes`."""
    if not orphan_ids:
        return []
    return [
        Finding(
            oracle="orphans",
            summary=f"{check_name}: {len(orphan_ids)} orphaned row(s)",
            evidence={"sample_ids": orphan_ids},
        )
    ]
