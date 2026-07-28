"""Finding record + rendering shared by every #400 oracle."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Finding:
    oracle: str  # "graph" | "counts" | "ciphertext" | "logscan" | "orphans" | "oracle-error"
    summary: str
    evidence: dict = field(default_factory=dict)


def render_text(findings: list[Finding], suppressed: int = 0) -> str:
    lines = [f"{len(findings)} finding(s), {suppressed} suppressed (allowlisted)."]
    for f in findings:
        lines.append(f"[{f.oracle}] {f.summary}")
        for k, v in f.evidence.items():
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def render_json(findings: list[Finding], suppressed: int = 0) -> str:
    return json.dumps(
        {"count": len(findings), "suppressed": suppressed, "findings": [asdict(f) for f in findings]},
        indent=2,
        default=str,
    )
