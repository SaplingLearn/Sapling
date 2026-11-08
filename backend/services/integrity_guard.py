"""Spec §13 A125: the integrity guard of the AI surfaces OUTSIDE the learning loop.

The loop scans every tutor turn it serves against the student's posed items
(A88, A93, A101, A105), but no other AI surface knew those items: a student
could paste an open check into the notes chat, get its answer there, then
submit it for full unassisted credit. Every student-facing surface that hands a
model text the student typed or pasted at request time now runs this guard —
the notes chat, summary and concept extraction (routes/notes.py) and the
flashcard generators (routes/flashcards.py):

1. ONE bounded read per request of the student's posed-and-ungraded items: the
   loop's own scan set, `routes.learn_loop.posed_items` (A93/A101 — every open
   check, open review item and unanswered post-test pose, the ungraded steps of
   ended sessions and the ledger's posed rows; the newest LOOP_SCAN_POSED_MAX,
   loaded in batched reads). Both checks below use that one read.
2. Before the model call (`open_guard`): when the student's text quotes one of
   those items' stems (learning.stem_match — the leak guards' fold, tokens and
   stem rule; no model call) the model is NOT called. The surface serves the
   deterministic integrity response (REFUSED_REPLY / REFUSED_DETAIL), pointing
   back to the item's card and its hint ladder, and a 'help' row at
   INTEGRITY_HELP_RUNG is recorded on each quoted item, so a later grade of it
   carries no unassisted credit (A93: the student sought outside help).
3. After the model call (`Guard.screen`, `Guard.screen_each`): the text the
   surface would serve is scanned against the same items (learning.served_scan,
   strict served mode, the student's own text as the provenance, A101). Text
   that states an item's key is withheld (WITHHELD_REPLY / WITHHELD_DETAIL; a
   list output loses only the elements that state one) and the item gets the
   same help row: a withholding answers "was that the key?", the yes/no oracle
   A86 retired withholding for in the loop, so it floors the item too.
4. Items that cannot be read (or a scan that raises): the model text is served
   and an 'unscanned' marker recorded, so every posed item at or before it
   grades as assisted; items beyond the window: a marker at the window's edge
   (A88 (c), A93). Once per request, only when model text is served.

Every write follows the accepted DB-down rule (an ERROR is logged; a refusal or
a withholding stands). Event `learn.outside_leak` {surface, stage,
question_hashes, count, help_recorded}: hashes and enums only, never the
student's or the model's text (learning.zpd_events). The guard is part of the
loop: the route passes `learning_loop_for_request`, and under the kill switch
the guard reads, refuses and withholds nothing (§11.6 restores the pre-loop app).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from learning.help_ledger import record_help
from learning.params import INTEGRITY_HELP_RUNG
from learning.reveal_store import record_unscanned

# The PKG-06 layer (learning.leak, learning.zpd_events — reached through
# learning.served_scan and learning.stem_match) is imported inside the methods
# that run only on an ACTIVE guard, i.e. after the route's learning-loop gate
# returned True: booting the app, or any request under the kill switch, loads
# none of it (tests/test_learning_zpd_policy.py's inertness scan and app-load
# probe; tests/test_learning_outside_integrity.py pins the inactive path).

logger = logging.getLogger(__name__)

#: the help ledger's `source` for the guard's rows (learning.help_ledger.SOURCES)
SOURCE = "outside"
#: the surfaces the guard runs on (learn.outside_leak's `surface`)
SURFACES = ("note_chat", "note_summary", "note_concepts", "flashcards")

# In-band replies (the notes chat answers in its own panel).
REFUSED_REPLY = (
    "That's one of your open learning checks, so I can't help with it here. Go "
    "back to its card in your learning session: the hints there walk you through "
    "it one step at a time. Because you brought it here, that check will count as "
    "helped rather than solved on your own."
)
WITHHELD_REPLY = (
    "I held that reply back because it would give away the answer to one of your "
    "open learning checks. Work through that check on its card in your learning "
    "session, where the hints go one step at a time. Since my reply touched on its "
    "answer, that check will count as helped rather than solved on your own."
)
# 409 details for the action surfaces: the frontend toast shows a server detail
# only when it is short plain prose (lib/errorMessage.ts: 160 characters, no
# brackets or line breaks), so these stay within that.
REFUSED_DETAIL = (
    "This includes one of your open learning checks. Use the hints on its card "
    "in your learning session instead. That check now counts as helped."
)
WITHHELD_DETAIL = (
    "This would give away the answer to one of your open learning checks, so it "
    "was held back. That check now counts as helped."
)


def _posed(user_id: str):
    """The loop's own scan set (A93/A101), `routes.learn_loop.posed_items`:
    ([(item, first posed at)], overflow edge), or None when it cannot be read.
    Imported at call time — the route module imports the loop's whole agent
    stack, and services must not load it at import (the services/quiz_signals
    precedent)."""
    from routes.learn_loop import posed_items

    return posed_items(user_id, now=datetime.now(timezone.utc))


@dataclass
class Guard:
    """One request's guard: the student's posed items (read once), what the
    request's own text quoted, and what has been recorded so far."""

    user_id: str
    surface: str
    request_id: str | None = None
    active: bool = False
    items: list = field(default_factory=list)
    overflow: datetime | None = None
    unreadable: bool = False
    given: str = ""  # the student's request-time text: the served scan's provenance
    quoted: list[str] = field(default_factory=list)
    _scan: Any = None  # learning.served_scan.ScanSet, built on the first scan
    _given_folded: Any = None  # learning.stem_match.Folded of `given`, on first use
    _marked: bool = False

    @property
    def refused(self) -> bool:
        """The student's text quoted a posed item: the model must not be called."""
        return bool(self.quoted)

    # ── the scan of what the surface would serve ────────────────────────────

    def _stated(self, text: str) -> tuple[list[str], bool]:
        """(the hashes `text` states, whether the scan ran). An item whose rules
        cannot be built counts as stated (ScanSet, fail closed); a scan that
        raises is no scan (the caller serves under an 'unscanned' marker, A105)."""
        if not self.items or not text:
            return [], True
        try:
            if self._scan is None:
                from learning.served_scan import ScanSet  # active guard only (module comment)

                self._scan = ScanSet.build(self.items, given=self.given)
            return self._scan.stated(text), True
        except Exception:
            logger.error("%s text could not be scanned", self.surface, exc_info=True)
            return [], False

    def screen(self, text: str) -> bool:
        """Whether the surface may serve `text`. False: it states the key of a
        posed item — withheld; help recorded on each such item; event emitted."""
        return self.screen_each([text])[0]

    def screen_each(
        self, texts: Sequence[str], *, own: Callable[[str], bool] | None = None
    ) -> list[bool]:
        """`screen` for a list output (flashcards, concept names): one flag per
        element; only the elements that state a key are withheld, and the help
        rows and the event cover all of them. `own(text)` True: the element is
        the student's own text (a concept name their note holds), not scanned."""
        if not self.active:
            return [True] * len(texts)
        keep: list[bool] = []
        stated: set[str] = set()
        scanned = True
        for text in texts:
            if own is not None and own(text):
                keep.append(True)
                continue
            hashes, ran = self._stated(text)
            scanned = scanned and ran
            stated.update(hashes)
            keep.append(not hashes)
        if stated:
            recorded = self._record_help(stated)
            self._emit("reply", stated, recorded)
        if any(keep):
            self._served(scan_failed=not scanned)
        return keep

    # ── records ──────────────────────────────────────────────────────────────

    def _record_help(self, hashes) -> bool:
        """A93 help rows at INTEGRITY_HELP_RUNG (the accepted DB-down rule: an
        ERROR per failed write; what the surface does stands)."""
        ok = True
        for qh in sorted(set(hashes)):
            try:
                record_help(self.user_id, qh, INTEGRITY_HELP_RUNG, source=SOURCE)
            except Exception:
                ok = False
                logger.error("integrity help row of %s not recorded", self.surface, exc_info=True)
        return ok

    def _served(self, *, scan_failed: bool = False) -> None:
        """Model text was served: when the items could not be read (or the scan
        raised), an 'unscanned' marker now — every posed item at or before it
        grades as assisted; when items lie beyond the window, one at the window's
        edge (A88 (c), A93). Once per request."""
        if self._marked:
            return
        blind = self.unreadable or scan_failed
        at = datetime.now(timezone.utc) if blind else self.overflow
        if at is None:
            return
        self._marked = True
        try:
            record_unscanned(
                self.user_id, session_id=None, source=f"{SOURCE}:{self.surface}", at=at
            )
        except Exception:
            logger.error("unscanned marker of %s LOST", self.surface, exc_info=True)
        if blind:
            self._emit("unscanned", (), False)

    def _emit(self, stage: str, hashes, recorded: bool) -> None:
        """learn.outside_leak (stage: zpd_events.OutsideStage)."""
        from learning import zpd_events  # active guard only (module comment)

        zpd_events.emit_outside_leak(
            user_id=self.user_id,
            request_id=self.request_id,
            surface=self.surface,
            stage=stage,
            question_hashes=sorted(set(hashes)),
            help_recorded=recorded,
        )

    # ── concept names (note_concepts) ────────────────────────────────────────

    def own_text(self, text: str) -> bool:
        """`text` (a concept name) is a whole run of the student's own request
        text, up to inflection: the note named it, so naming it adds nothing."""
        from learning.stem_match import Folded, tokens  # active guard only (module comment)

        run = tuple(t.value for t in tokens(text))
        if not run:
            return False
        if self._given_folded is None:
            self._given_folded = Folded.of(self.given)
        return self._given_folded.holds(run)


def open_guard(
    user_id: str,
    *,
    surface: str,
    texts: Sequence[str | None],
    active: bool,
    request_id: str | None = None,
) -> Guard:
    """The request's guard: ONE read of the student's posed items and the
    pre-call check of `texts` — the text the student typed or pasted, as the
    model will read it. Quoted → `refused`, a help row on each quoted item and
    learn.outside_leak (stage `request`). Inactive (`active` False: the loop is
    off): reads nothing, refuses nothing, withholds nothing. Synchronous (the
    reads are DB calls): async routes run it in a worker thread."""
    if surface not in SURFACES:
        raise ValueError(f"unknown integrity surface {surface!r}")
    guard = Guard(user_id=user_id, surface=surface, request_id=request_id, active=bool(active))
    if not guard.active:
        return guard
    guard.given = "\n\n".join(t for t in texts if t)
    got = _posed(user_id)
    if got is None:  # posed_items logged it: served under an 'unscanned' marker
        guard.unreadable = True
        return guard
    pairs, guard.overflow = got
    guard.items = [item for item, _at in pairs]
    try:
        from learning.stem_match import StemSet  # active guard only (module comment)

        guard.quoted = StemSet.build(guard.items).quoted(guard.given)
    except Exception:
        logger.error("%s request could not be matched against posed items", surface, exc_info=True)
        guard.unreadable = True
        return guard
    if guard.quoted:
        guard._emit("request", guard.quoted, guard._record_help(guard.quoted))
    return guard
