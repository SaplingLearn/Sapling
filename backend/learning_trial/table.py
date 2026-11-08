"""The trial's de-identified long table: one row per (student, concept, post-test
window). `scripts/export_learning_trial.py` writes it from the database;
`learning_trial.simulate` generates it synthetically; `learning_trial.analysis`
reads it. Ids are pseudonyms (salted hashes, `learning_trial.deidentify`) and no
row carries text: booleans, enums, small numbers and pseudonyms only.

Columns (CSV header order):

    student              pseudonymous student id
    course               pseudonymous course id ("" when unknown)
    concept              pseudonymous COURSE-LEVEL concept id (course + concept
                         key), so students of one course share a concept id:
                         the crossed random effect / clustering dimension
    arm                  "treatment" | "control" (assigned, intention to treat)
    window               post-test window in days (spec §13 A112: 7 or 28)
    pretest              1 | 0 | "" — the concept's probe pretest (A112), "" when
                         the concept has no usable pretest
    posttest             1 | 0 | "" — the unassisted (rung-0) post-test outcome;
                         set only when status is "rung0"
    status               rung0 | assisted | unrecorded | open | expired | not_posed
    exclusion            "" | retired_item | reported_item
    item                 pseudonymous post-test item id ("" when nothing posed)
    days_since_evidence  days from the concept's last evidence to the pose. It is
                         POST-randomization (the loop's own practice moves it), so
                         it is descriptive only and never a model covariate.
    cov_<name>           optional numeric PRE-randomization covariates

A row is analyzable (`analyzable`) when its status is rung0, it has a post-test
outcome and no exclusion; every other row is a missing outcome, kept so
attrition can be reported per arm.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

TREATMENT = "treatment"
CONTROL = "control"
ARMS = (TREATMENT, CONTROL)

#: post-test outcome states (A112 / A89): a rung-0 graded answer; a graded answer
#: that carried help or no credit (max_rung > 0); an answer from before A112
#: recorded no outcome; a live pose; a pose that expired unanswered (void); a
#: window that opened with nothing posed.
STATUSES = ("rung0", "assisted", "unrecorded", "open", "expired", "not_posed")
#: item-level exclusions (A113): the item was retired as broken, or it carries a
#: student report no later staff approval cleared.
EXCLUSIONS = ("", "retired_item", "reported_item")

COLUMNS = (
    "student",
    "course",
    "concept",
    "arm",
    "window",
    "pretest",
    "posttest",
    "status",
    "exclusion",
    "item",
    "days_since_evidence",
)
COVARIATE_PREFIX = "cov_"


class TableError(ValueError):
    """A long-table row or file that does not meet the schema."""


@dataclass(frozen=True, slots=True)
class TrialRow:
    student: str
    concept: str
    arm: str
    window: int
    pretest: bool | None
    posttest: bool | None
    status: str = "rung0"
    exclusion: str = ""
    course: str = ""
    item: str = ""
    days_since_evidence: float | None = None
    covariates: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not self.student or not self.concept:
            raise TableError("student and concept are required")
        if self.arm not in ARMS:
            raise TableError(f"arm must be one of {ARMS}, got {self.arm!r}")
        if isinstance(self.window, bool) or not isinstance(self.window, int) or self.window <= 0:
            raise TableError(f"window must be a positive int, got {self.window!r}")
        if self.status not in STATUSES:
            raise TableError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.exclusion not in EXCLUSIONS:
            raise TableError(f"exclusion must be one of {EXCLUSIONS}, got {self.exclusion!r}")
        if self.posttest is not None and self.status != "rung0":
            raise TableError("a post-test outcome is recorded only for status rung0")
        for value in (self.pretest, self.posttest):
            if value is not None and not isinstance(value, bool):
                raise TableError("pretest and posttest are bool or None")

    def covariate(self, name: str) -> float | None:
        for key, value in self.covariates:
            if key == name:
                return value
        return None


def analyzable(row: TrialRow) -> bool:
    """An unassisted outcome on a valid item: the rows the analysis models."""
    return row.status == "rung0" and row.posttest is not None and not row.exclusion


def select(rows: Iterable[TrialRow], windows: Sequence[int]) -> list[TrialRow]:
    """The analyzable rows of the given windows."""
    wanted = set(windows)
    return [r for r in rows if r.window in wanted and analyzable(r)]


def _flag(value: bool | None) -> str:
    return "" if value is None else ("1" if value else "0")


def _parse_flag(raw: str, column: str, line: int) -> bool | None:
    raw = raw.strip()
    if raw == "":
        return None
    if raw in ("1", "0"):
        return raw == "1"
    raise TableError(f"line {line}: {column} must be 1, 0 or empty, got {raw!r}")


def _parse_float(raw: str, column: str, line: int) -> float | None:
    raw = raw.strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        raise TableError(f"line {line}: {column} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise TableError(f"line {line}: {column} must be finite")
    return value


def write_csv(rows: Iterable[TrialRow], out: str | Path | IO[str]) -> int:
    """Write the long table; returns the number of rows written. Covariate
    columns are the union of every row's covariates, sorted."""
    rows = list(rows)
    cov_names = sorted({name for r in rows for name, _ in r.covariates})
    header = list(COLUMNS) + [COVARIATE_PREFIX + n for n in cov_names]

    def emit(handle: IO[str]) -> None:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for r in rows:
            covs = dict(r.covariates)
            writer.writerow(
                [
                    r.student,
                    r.course,
                    r.concept,
                    r.arm,
                    r.window,
                    _flag(r.pretest),
                    _flag(r.posttest),
                    r.status,
                    r.exclusion,
                    r.item,
                    "" if r.days_since_evidence is None else f"{r.days_since_evidence:.1f}",
                ]
                + ["" if covs.get(n) is None else repr(float(covs[n])) for n in cov_names]
            )

    if isinstance(out, (str, Path)):
        with open(out, "w", newline="", encoding="utf-8") as handle:
            emit(handle)
    else:
        emit(out)
    return len(rows)


def read_csv(source: str | Path | IO[str]) -> list[TrialRow]:
    """Read a long table written by `write_csv` (or by hand to the same schema).
    Unknown columns are refused, so a column carrying anything but the schema
    (a raw id, a name, text) is never silently read past."""
    if isinstance(source, (str, Path)):
        with open(source, newline="", encoding="utf-8") as handle:
            return read_csv(io.StringIO(handle.read()))
    reader = csv.DictReader(source)
    header = reader.fieldnames or []
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise TableError(f"missing columns: {missing}")
    unknown = [c for c in header if c not in COLUMNS and not c.startswith(COVARIATE_PREFIX)]
    if unknown:
        raise TableError(f"unknown columns: {unknown}")
    cov_columns = [c for c in header if c.startswith(COVARIATE_PREFIX)]
    rows: list[TrialRow] = []
    for line, rec in enumerate(reader, start=2):
        try:
            window = int(rec["window"])
        except ValueError:
            raise TableError(f"line {line}: window must be an integer") from None
        covs = []
        for column in cov_columns:
            value = _parse_float(rec[column], column, line)
            if value is not None:
                covs.append((column[len(COVARIATE_PREFIX) :], value))
        try:
            rows.append(
                TrialRow(
                    student=rec["student"],
                    concept=rec["concept"],
                    arm=rec["arm"],
                    window=window,
                    pretest=_parse_flag(rec["pretest"], "pretest", line),
                    posttest=_parse_flag(rec["posttest"], "posttest", line),
                    status=rec["status"],
                    exclusion=rec["exclusion"],
                    course=rec["course"],
                    item=rec["item"],
                    days_since_evidence=_parse_float(rec["days_since_evidence"], "days_since_evidence", line),
                    covariates=tuple(covs),
                )
            )
        except TableError as exc:
            raise TableError(f"line {line}: {exc}") from None
    return rows


def counts_by(rows: Iterable[TrialRow], *keys: str) -> dict[tuple, int]:
    """Row counts per combination of the named attributes (for flow tables)."""
    out: dict[tuple, int] = {}
    for r in rows:
        key = tuple(getattr(r, k) for k in keys)
        out[key] = out.get(key, 0) + 1
    return out


def covariate_names(rows: Iterable[TrialRow]) -> list[str]:
    return sorted({name for r in rows for name, _ in r.covariates})


def as_mapping(row: TrialRow) -> Mapping[str, object]:
    """A row as a plain mapping (for the optional pandas path)."""
    out: dict[str, object] = {c: getattr(row, c) for c in COLUMNS}
    out.update({COVARIATE_PREFIX + k: v for k, v in row.covariates})
    return out
