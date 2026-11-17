"""The item id a structured check answer names, as the prompt listed it.

The batched checks (the A119 alignment check, the A124 blind solve and key
match, the A145 quiz gates) show each item under an `ITEM <id>` line and ask
for the id back. Claude sometimes echoes the whole label, `"ITEM 3"`, instead
of `"3"` (seen 2026-11-17 on check_items_solve: every answer of a batch was
then unmatched and every draft dropped as unverified). Only that label is
removed — the remainder must still equal a listed id exactly, so nothing
loosens the "ids are matched exactly, an unlisted id is ignored" rule.
"""

from __future__ import annotations

import re

_LABEL = re.compile(r"^item[\s:#]+(?=\S)", re.IGNORECASE)


def echoed_id(raw: object) -> str:
    """``raw`` stripped, without a leading ``ITEM`` label (``"ITEM 3"``,
    ``"item: 3"``, ``"Item #3"`` → ``"3"``). An id that merely starts with
    the letters (``"item-3"``, ``"items"``) is left as it is."""
    return _LABEL.sub("", str(raw).strip(), count=1).strip()
