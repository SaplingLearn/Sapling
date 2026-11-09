"""An event loop whose clock a test moves, so a deadline never races the machine."""

from __future__ import annotations

import asyncio


class ManualClockLoop(asyncio.SelectorEventLoop):
    """The default Unix loop, but only the test can move its clock past a deadline.

    `asyncio.wait_for` arms its deadline from `loop.time()`, so skipping this
    clock ahead decides exactly when the deadline expires: wall-clock speed
    (a busy machine, a slow thread hop) never does. Use it as
    `asyncio.run(main(), loop_factory=ManualClockLoop)` and call
    `asyncio.get_running_loop().advance(seconds)` at the moment the deadline
    should pass.
    """

    def __init__(self):
        super().__init__()
        self.skipped = 0.0

    def time(self):
        return super().time() + self.skipped

    def advance(self, seconds):
        self.skipped += seconds
