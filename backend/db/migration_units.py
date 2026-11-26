"""Read migrations as the units they were written in.

#866's 62 migrations were consolidated into one file before any environment
applied them (staging and production had none of them in their ledgers). The
runner (`db/migrate.py`) applies that file as one migration, in one
transaction. Its SQL is the 62 files' SQL, concatenated in filename order;
each original starts at a `-- @@ unit <original filename>` line, so tests,
scripts and docs can still name the migration a change came from.

`units()` yields every migration in apply order as (name, sql): a plain file
as itself, a consolidated file as its units in place. `unit_sql(name)` reads
one unit by its name, whichever file holds it.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterator
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

#: The line that starts a unit inside a consolidated migration.
UNIT_MARKER = re.compile(r"^-- @@ unit (\S+\.sql)[ \t]*$", re.MULTILINE)


def split_units(path: Path) -> list[tuple[str, str]]:
    """The units in one migration file: itself, or its marked sections."""
    sql = path.read_text(encoding="utf-8")
    marks = list(UNIT_MARKER.finditer(sql))
    if not marks:
        return [(path.name, sql)]
    out = []
    for mark, nxt in zip(marks, [*marks[1:], None], strict=True):
        out.append((mark.group(1), sql[mark.end() + 1 : nxt.start() if nxt else len(sql)]))
    return out


def units(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, str]]:
    """Every migration unit, in the order the runner applies them."""
    out: list[tuple[str, str]] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        out.extend(split_units(path))
    return out


def unit_sql(name: str, migrations_dir: Path = MIGRATIONS_DIR) -> str:
    """One unit's SQL by its (original) filename."""
    for unit, sql in units(migrations_dir):
        if unit == name:
            return sql
    raise FileNotFoundError(f"no migration unit {name!r} in {migrations_dir}")


def unit_names(migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    return [name for name, _ in units(migrations_dir)]


class UnitPath:
    """One unit, read like a migration file (`name`, `stem`, `read_text`)."""

    def __init__(self, name: str, sql: str | None) -> None:
        self.name = name
        self.stem = name.removesuffix(".sql")
        self._sql = sql

    def exists(self) -> bool:
        return self._sql is not None

    def read_text(self, encoding: str | None = None) -> str:
        if self._sql is None:
            raise FileNotFoundError(f"no migration unit {self.name!r}")
        return self._sql

    def __lt__(self, other: UnitPath) -> bool:
        return self.name < other.name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, UnitPath) and other.name == self.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __repr__(self) -> str:
        return f"UnitPath({self.name!r})"


class UnitDir:
    """The migrations directory as its units: `glob` and `/` find a unit by its
    original filename whether it is a file or a section of a consolidated one,
    so a test that reads a migration by name reads the same SQL as before."""

    def __init__(self, migrations_dir: Path = MIGRATIONS_DIR) -> None:
        self.path = migrations_dir
        self._cache: dict[str, str] | None = None

    def _units(self) -> dict[str, str]:
        # Read once per process: migrations never change while one runs.
        if self._cache is None:
            self._cache = dict(units(self.path))
        return self._cache

    def glob(self, pattern: str) -> Iterator[UnitPath]:
        """Like Path.glob: an iterator, in filename order."""
        return iter(
            [UnitPath(n, s) for n, s in sorted(self._units().items()) if fnmatch.fnmatchcase(n, pattern)]
        )

    def __truediv__(self, name: str) -> UnitPath:
        return UnitPath(name, self._units().get(name))


#: The migrations directory, read as units (tests and release checks).
MIGRATION_UNITS = UnitDir()
