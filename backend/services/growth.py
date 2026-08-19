"""The level curve, derived from the growth_stages table.

growth_stages is the single source of truth for level maths: the hero card,
the leaderboard's stage label and the `level` achievement trigger all read it
through here, so there is exactly one answer to "what stage is level 17".

Each stage band declares the XP needed to cross it. A level inside a band
costs `xp_to_complete / span`, where span is the distance to the next band's
min_level. The terminal band has no xp_to_complete and costs nothing.
"""

from functools import lru_cache

from db.connection import table


@lru_cache(maxsize=1)
def _stages_cached() -> tuple:
    rows = table("growth_stages").select(
        "slug,name,blurb,min_level,xp_to_complete,sort_order",
        order="sort_order.asc",
    )
    return tuple(rows or [])


def stages() -> list[dict]:
    """The stage bands, ascending. Each row is copied shallowly (`dict(r)`) so
    callers can't mutate the cached tuple — sufficient because growth_stages
    rows are flat (scalar columns only, no nested mutable values)."""
    return [dict(r) for r in _stages_cached()]


def clear_growth_cache() -> None:
    """#98: every growth_stages mutator must call this."""
    _stages_cached.cache_clear()


def _bands() -> list[dict]:
    """Stages annotated with the span and per-level cost of each band.

    Sorted explicitly by min_level: sort_order and min_level are independent
    columns (20260731193214_gamification.sql ties neither to the other), so the query's
    sort_order.asc ordering is not guaranteed to match ascending min_level.
    _band_for_level's early-exit scan — and this function's own span
    computation, which looks at the *next* row's min_level — both depend on
    that ordering being correct.
    """
    rows = sorted(stages(), key=lambda r: r["min_level"])
    out = []
    for i, s in enumerate(rows):
        nxt = rows[i + 1]["min_level"] if i + 1 < len(rows) else None
        span = (nxt - s["min_level"]) if nxt else 0
        cost = s.get("xp_to_complete")
        out.append({
            **s,
            "span": span,
            "per_level": (cost // span) if (cost and span) else 0,
        })
    return out


def _band_for_level(level: int) -> dict | None:
    band = None
    for b in _bands():
        if level >= b["min_level"]:
            band = b
        else:
            break
    return band


def xp_for_level(level: int) -> int:
    """XP needed to go from `level` to `level + 1`. 0 at the terminal stage."""
    band = _band_for_level(level)
    return band["per_level"] if band else 0


def stage_for_level(level: int) -> dict:
    band = _band_for_level(level)
    if band:
        return {k: v for k, v in band.items() if k not in ("span", "per_level")}
    first = stages()
    return first[0] if first else {}


def max_level() -> int:
    rows = stages()
    return rows[-1]["min_level"] if rows else 1


def level_for_xp(total_xp: int) -> int:
    """Walk the curve from level 1, spending XP, until it runs out or we cap."""
    cap = max_level()
    level, spent = 1, 0
    while level < cap:
        cost = xp_for_level(level)
        # Only the terminal band is expected to have a non-positive per-level
        # cost. A non-terminal band misconfigured with xp_to_complete 0/NULL
        # would also break here, silently stranding the user at this level
        # forever (no error) rather than looping infinitely.
        if cost <= 0 or spent + cost > total_xp:
            break
        spent += cost
        level += 1
    return level


def xp_into_level(total_xp: int) -> tuple[int, int]:
    """(xp earned into the current level, xp the current level costs)."""
    level = level_for_xp(total_xp)
    cap = max_level()

    # At terminal level, no progress to track.
    if level == cap:
        return (0, 0)

    spent = 0
    for lv in range(1, level):
        spent += xp_for_level(lv)
    return total_xp - spent, xp_for_level(level)
