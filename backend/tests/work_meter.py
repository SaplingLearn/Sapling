"""Linear-time checks that do not depend on how fast or busy the machine is.

`count_work(fn)` runs `fn()` under `sys.monitoring` and counts the work it does
in units that are the same on every run:

- `steps`: every call made from Python code (to a Python function or a C
  builtin, a regex method included) plus every jump in Python code, which
  includes each loop iteration;
- `chars`: the length of every str a str method runs on. A method such as
  `casefold`, `split` or `rfind` costs time in proportion to its str, so a
  per-match rescan of the whole text shows up here even when the number of
  calls stays linear. A search given a start position (`text.startswith(p, i)`)
  is not counted: it may read only a few characters.

`assert_linear` measures the work at n/4, n/2 and n, after one warm-up run that
absorbs one-time work such as compiling a regex. Work that grows linearly adds
the same amount per extra character, so the second doubling adds twice what the
first did; work that grows quadratically adds four times as much.

What these counts cannot see is the steps a regex engine takes inside one
call: `re` runs in C and reports nothing back. Catastrophic backtracking is
caught by `cpu_seconds` instead, a coarse ceiling on the thread's own CPU time.
CPU time does not include time spent waiting for a busy machine to run the
thread, which is what made the old wall-clock limits flaky.
"""

from __future__ import annotations

import dis
import gc
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, fields

# The second doubling may add at most this multiple of what the first added
# (plus n, so a count that barely moves is not judged on its rounding): 2 for
# linear work, 4 for quadratic. Halfway leaves room for the uneven tail when an
# input is cut from a repeated unit.
DOUBLING_LIMIT = 3.0

# str methods whose second argument is a start position.
_POSITIONED = frozenset({"find", "rfind", "index", "rindex", "count", "startswith", "endswith"})


@dataclass(frozen=True)
class Work:
    steps: int
    chars: int


def count_work(fn: Callable[[], object]) -> Work:
    mon = sys.monitoring
    # A coverage run may hold a tool id of its own; take any free one.
    tool = next(i for i in range(6) if mon.get_tool(i) is None)
    steps = chars = 0
    arg_counts: dict[object, dict[int, int]] = {}

    def positional_args(code, offset) -> int | None:
        if code not in arg_counts:
            arg_counts[code] = {
                i.offset: i.arg for i in dis.get_instructions(code) if i.opname in ("CALL", "CALL_KW")
            }
        return arg_counts[code].get(offset)

    def on_call(code, offset, callable_, arg0):
        nonlocal steps, chars
        steps += 1
        if getattr(callable_, "__objclass__", None) is str and isinstance(arg0, str):
            if callable_.__name__ in _POSITIONED and (positional_args(code, offset) or 0) > 1:
                return
            chars += len(arg0)

    def on_jump(code, offset, destination):
        nonlocal steps
        steps += 1

    mon.use_tool_id(tool, "work_meter")
    try:
        mon.register_callback(tool, mon.events.CALL, on_call)
        mon.register_callback(tool, mon.events.JUMP, on_jump)
        mon.set_events(tool, mon.events.CALL | mon.events.JUMP)
        fn()
    finally:
        mon.set_events(tool, 0)
        mon.register_callback(tool, mon.events.CALL, None)
        mon.register_callback(tool, mon.events.JUMP, None)
        mon.free_tool_id(tool)
    return Work(steps, chars)


def assert_linear(
    build: Callable[[int], object],
    run: Callable[[object], object],
    n: int,
    label: str = "",
    *,
    counts: tuple[str, ...] = tuple(f.name for f in fields(Work)),
) -> None:
    """`build(size)` makes an input of `size` (not counted); `run(input)` is the
    work that is counted. n is the largest size. `counts` names the counts that
    must grow linearly (both, unless a caller documents why one may not)."""
    run(build(n // 4))
    quarter, half, full = (
        count_work(lambda arg=build(size): run(arg)) for size in (n // 4, n // 2, n)
    )
    for name in counts:
        a, b, c = (getattr(w, name) for w in (quarter, half, full))
        first, second = b - a, c - b
        assert second <= DOUBLING_LIMIT * first + n, (
            f"{label}: {name} grew superlinearly: "
            f"{a} at n/4, {b} at n/2, {c} at n (doublings added {first}, then {second})"
        )


class _Runaway(Exception):
    pass


def _stop_runaway(signum, frame):
    raise _Runaway


def cpu_seconds(fn: Callable[[], object], *, limit: float, repeats: int = 3) -> float:
    """The least CPU time this thread spent in `fn()` over up to `repeats` runs,
    stopping at the first run under `limit`. The garbage collector is paused so
    a collection of the whole test session's heap is not billed to `fn`.

    A run still going after ten times the limit (at least 5 s) of CPU time is
    stopped by a CPU-time timer (SIGPROF, which also interrupts a regex), and
    that stopping point is returned: an exponential regression then fails the
    test instead of hanging it. Main thread only, as signal handlers are."""
    best = float("inf")
    stop_at = max(10 * limit, 5.0)
    was_enabled = gc.isenabled()
    previous = signal.signal(signal.SIGPROF, _stop_runaway)
    gc.disable()
    try:
        for _ in range(repeats):
            start = time.thread_time()
            signal.setitimer(signal.ITIMER_PROF, stop_at)
            try:
                fn()
            except _Runaway:
                return stop_at
            finally:
                signal.setitimer(signal.ITIMER_PROF, 0)
            best = min(best, time.thread_time() - start)
            if best < limit:
                break
    finally:
        signal.signal(signal.SIGPROF, previous)
        if was_enabled:
            gc.enable()
    return best
