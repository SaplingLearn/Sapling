"""In-memory PostgREST stand-in shared by the local seed tests."""
from collections import defaultdict
from copy import deepcopy


def _matches(stored, expr: str) -> bool:
    """The PostgREST operators the seed code uses: eq., in.(a,b), like.prefix*."""
    if expr.startswith("in.(") and expr.endswith(")"):
        return str(stored) in expr[4:-1].split(",")
    if expr.startswith("like."):
        pattern = expr.removeprefix("like.")
        assert pattern.endswith("*") and "*" not in pattern[:-1], pattern
        # SQL LIKE: `_` matches any one character, exactly as PostgREST would.
        prefix = pattern[:-1]
        return isinstance(stored, str) and len(stored) >= len(prefix) and all(
            want in ("_", got) for want, got in zip(prefix, stored)
        )
    return str(stored) == expr.removeprefix("eq.")


class MemoryDatabase:
    """Persist writes between CLI runs, rather than echoing mocked payloads."""

    def __init__(self):
        self.rows = defaultdict(list)
        self.writes = []

    def table(self, name):
        db = self

        class Handle:
            def select(self, columns="*", filters=None, limit=None, offset=None, order=None):
                rows = [row for row in db.rows[name] if all(
                    _matches(row.get(key), value) for key, value in (filters or {}).items()
                )]
                if order:
                    rows = sorted(rows, key=lambda row: row.get("id", ""))
                rows = rows[offset or 0:]
                if limit:
                    rows = rows[:limit]
                return deepcopy(rows)

            def select_with_count(self, columns="*", filters=None, limit=None, offset=None, order=None):
                count = len(self.select(columns, filters=filters))
                return self.select(columns, filters=filters, limit=limit, offset=offset, order=order), count

            def insert(self, row):
                if row.get("id"):
                    assert not any(saved.get("id") == row["id"] for saved in db.rows[name])
                db.rows[name].append(deepcopy(row))
                db.writes.append((name, "insert"))
                return [deepcopy(row)]

            def update(self, row, filters):
                matching = self.select(filters=filters)
                for saved in db.rows[name]:
                    if saved in matching:
                        saved.update(deepcopy(row))
                db.writes.append((name, "update"))
                return self.select(filters=filters)

            def upsert(self, row, on_conflict):
                filters = {key: f"eq.{row[key]}" for key in on_conflict.split(",")}
                if self.select(filters=filters):
                    return self.update(row, filters)
                return self.insert(row)

        return Handle()
