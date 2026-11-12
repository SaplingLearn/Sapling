"""The section writer's text as items.

`agents.study_guide.study_guide_section_agent` writes a section as text, in a
small markup (its system prompt is the other half of this file):

- Prose is plain paragraphs separated by blank lines. `**term**` marks a key
  term and is kept as written. `[S2]` cites the source labelled S2.
- A line that starts with `>>` is the Skim summary of the passage above it,
  and closes that passage. A line that starts with `>>>` is not: that is a
  Python prompt, and stays prose.
- A block is one JSON object inside a fence: a line ```` ```block ````, the
  JSON, a closing ```` ``` ````. It names its source by label: `"source": "S2"`.
- A fence with any other language (```` ```python ````) is a code sample. It
  stays in the prose as a paragraph of its own, fence included, so the
  reader's Markdown shows it as code. It ends at a bare fence and nowhere
  else, so nothing inside it is a block.
- A block fence that is never closed ends where its JSON object does, and the
  text after it is prose.

A passage is the run of paragraphs up to the next summary line or block. A run
longer than three paragraphs is split into further passages, and its summary
goes on the last of them.

Ids are assigned here, never by the model: `{section_id}-i{n}`, where n is the
item's 1-based place in the section. A block that fails validation keeps its
place, so a rewritten block can be put back where it belongs (`put_back`).

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from models.study_guide import BLOCK_TYPES, Block, Item, parse_items

_FENCE = "```"
#: The fence languages that hold a block. A bare fence does too.
_BLOCK_LANGUAGES = ("", "block", "json")
#: `Paragraph.text`'s cap. Prose past it is clipped at a word; a code sample
#: past it is dropped, because half a code sample is worse than none.
_CODE_MAX = 1200
#: Fields that hold LaTeX. A newline there is `\neq` or `\nu` written with
#: one backslash, never a line break.
_MATH_FIELDS = ("latex", "math")
#: Fields that hold a chart coordinate. Validation would read a JSON `true`
#: there as 1.0.
_COORDINATE_FIELDS = ("x", "y")
#: `## A heading` or a `---` rule: a model's habit, not part of the markup.
_NOISE = re.compile(r"\s{0,3}(#{1,6}\s.*|([-*_])(\s*\2){2,})\s*")
#: `[S1]` or `[S1, S3]`, with the space before it.
CITATION = re.compile(r"\s*\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]", re.IGNORECASE)
_TYPE_IN_BROKEN_JSON = re.compile(r'"type"\s*:\s*"(\w+)"')
_PASSAGE_PARAGRAPHS = 3
#: Fields the server decides, whatever the model wrote: `id` here, `source_id`
#: from the block's `source` label, and `illustrative`, which stays at its
#: default (True) until `services.study_guides.verify` rules on the chart.
_SERVER_FIELDS = ("id", "source", "source_id", "illustrative")


@dataclass(frozen=True)
class RejectedBlock:
    """A block that did not validate. `id` is the id it would have had."""

    id: str
    #: The block's `type` when it could be read, else None.
    type: str | None
    #: The JSON object as the model wrote it; empty when it did not parse.
    raw: dict
    #: The fence's content as written, for the rewrite prompt.
    text: str


@dataclass(frozen=True)
class ParsedSection:
    items: list[Item]
    rejected: list[RejectedBlock]


def parse_section(text: str, *, section_id: str, sources: dict[str, str]) -> ParsedSection:
    """One section's text as validated items, plus the blocks that failed.

    `sources` maps a label (`"S1"`) to a source id (`"document:<id>"`,
    `"quiz-history"`). A citation or `source` with an unknown label is dropped.
    """
    items: list[Item] = []
    rejected: list[RejectedBlock] = []
    for place, (kind, content, summary) in enumerate(_entries(_chunks(text)), start=1):
        item_id = f"{section_id}-i{place}"
        if kind == "prose":
            items.extend(_validated(_prose(content, summary, item_id, sources)))
            continue
        block, raw = _block(content, item_id, sources)
        if block is not None:
            items.append(block)
        else:
            rejected.append(_rejected(item_id, raw, content))
    return ParsedSection(items=items, rejected=rejected)


def parse_block(text: str, *, block_id: str, sources: dict[str, str]) -> Block | None:
    """The block agent's reply as one validated block, or None.

    The reply should be one fenced block; a bare JSON object is read too.
    """
    fenced = [content for kind, content in _chunks(text) if kind == "block"]
    block, _ = _block(fenced[0] if fenced else text, block_id, sources)
    return block


def put_back(items: list[Item], block: Block) -> list[Item]:
    """`items` with `block` at the place its id names: how a rejected block
    that was rewritten returns to its section."""
    place = _place(block.id)
    at = next((i for i, item in enumerate(items) if _place(item.id) > place), len(items))
    return [*items[:at], block, *items[at:]]


def _place(item_id: str) -> int:
    return int(item_id.rsplit("-i", 1)[1])


# ── Text to entries ───────────────────────────────────────────────────────────


def _chunks(text: str) -> list[tuple[str, str]]:
    """The text in order as `("paragraph" | "summary" | "block", content)`.
    A code sample is a paragraph whose content starts with a fence."""
    chunks: list[tuple[str, str]] = []
    prose: list[str] = []
    fenced: list[str] | None = None
    language = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        opens = stripped.startswith(_FENCE)
        if fenced is None and not opens:
            prose.append(line)
        elif fenced is None:
            chunks += _prose_chunks(prose)
            prose = []
            fenced, language = [], _language(stripped)
        elif stripped == _FENCE:
            chunks += _fence_chunks(language, fenced, closed=True)
            fenced = None
        elif opens and language in _BLOCK_LANGUAGES:
            # The block before was never closed, and the next fence opens.
            chunks += _fence_chunks(language, fenced, closed=False)
            fenced, language = [], _language(stripped)
        else:
            # A code sample ends at a bare fence only, as Markdown reads it,
            # so a fence line inside it is one of its lines.
            fenced.append(line)
    chunks += _prose_chunks(prose)
    if fenced is not None:
        chunks += _fence_chunks(language, fenced, closed=False)
    return chunks


def _language(fence_line: str) -> str:
    return fence_line[len(_FENCE):].strip().lower()


def _prose_chunks(lines: list[str]) -> list[tuple[str, str]]:
    """Lines outside any fence as paragraphs and summary lines."""
    chunks: list[tuple[str, str]] = []
    paragraph: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            chunks.append(("paragraph", " ".join(paragraph)))
            paragraph.clear()

    for line in lines:
        stripped = line.strip()
        if not stripped or _NOISE.fullmatch(line):
            close_paragraph()
        elif stripped.startswith(">>") and not stripped.startswith(">>>"):
            close_paragraph()
            chunks.append(("summary", stripped[2:].strip()))
        else:
            paragraph.append(stripped)
    close_paragraph()
    return chunks


def _fence_chunks(language: str, lines: list[str], *, closed: bool) -> list[tuple[str, str]]:
    """One fence's lines as chunks: a block, or a code sample (a paragraph).
    A fence that was never closed may hold prose after its block."""
    if language not in _BLOCK_LANGUAGES:
        # A reply cut inside a code sample ends the sample where it stopped.
        code = "\n".join([_FENCE + language, *lines, _FENCE])
        return [("paragraph", code)] if len(code) <= _CODE_MAX else []
    body = "\n".join(lines)
    if closed:
        return [("block", body)]
    block, after = _unclosed(language, body)
    blocks = [("block", block)] if block is not None else []
    return [*blocks, *_prose_chunks(after.split("\n"))]


def _unclosed(language: str, body: str) -> tuple[str | None, str]:
    """`(the block, the text after it)` of a block fence nothing closed.

    The block ends where its JSON object does, and the rest is ordinary text.
    A body that does not hold a whole object is all block: the reply was cut
    inside it, and it rejects. A bare fence followed by no JSON at all opened
    nothing (it is a closing fence with no partner), so its body is all text.
    """
    start = len(body) - len(body.lstrip())
    if not language and not body.startswith("{", start):
        return None, body
    try:
        value, end = json.JSONDecoder().raw_decode(body, start)
    except (ValueError, RecursionError):
        return body, ""
    return (body[:end], body[end:]) if isinstance(value, dict) else (body, "")


def _entries(chunks: list[tuple[str, str]]) -> list[tuple[str, object, str | None]]:
    """Chunks as the section's entries in order: `("block", body, None)` or
    `("prose", paragraphs, summary)`."""
    entries: list[tuple[str, object, str | None]] = []
    run: list[str] = []

    def close_run(summary: str | None = None) -> None:
        starts = range(0, len(run), _PASSAGE_PARAGRAPHS)
        for start in starts:
            last = start == starts[-1]
            passage = run[start : start + _PASSAGE_PARAGRAPHS]
            entries.append(("prose", passage, summary if last else None))
        run.clear()

    for kind, content in chunks:
        if kind == "paragraph":
            run.append(content)
        elif kind == "summary":
            # With no passage above it, a summary stands in for nothing.
            close_run(content)
        else:
            close_run()
            entries.append(("block", content, None))
    close_run()
    return entries


# ── Prose ─────────────────────────────────────────────────────────────────────


def _prose(paragraphs: list[str], summary: str | None, item_id: str, sources: dict[str, str]) -> dict:
    written = [_paragraph(text, sources) for text in paragraphs]
    return {
        "type": "prose",
        "id": item_id,
        "paragraphs": [paragraph for paragraph in written if paragraph["text"]],
        "summary": CITATION.sub("", summary or "").strip() or None,
    }


def _paragraph(text: str, sources: dict[str, str]) -> dict:
    if text.startswith(_FENCE):
        # A code sample: `a[S1]` in it is an index, not a citation.
        return {"text": text, "citations": []}
    cited: list[str] = []
    for match in CITATION.finditer(text):
        for label in match.group(1).split(","):
            source_id = sources.get(label.strip().upper())
            if source_id and source_id not in cited:
                cited.append(source_id)
    return {"text": CITATION.sub("", text).strip(), "citations": cited}


# ── Blocks ────────────────────────────────────────────────────────────────────


def _block(body: str, block_id: str, sources: dict[str, str]) -> tuple[Block | None, dict]:
    """`(the validated block or None, the JSON object as written or {})`."""
    raw = _json_object(body)
    try:
        sound = raw.get("type") in BLOCK_TYPES and not _unusable(raw)
    except RecursionError:  # nested too deep to walk
        sound = False
    if not sound:
        return None, raw
    valid = _validated(_prepared(raw, block_id, sources))
    return (valid[0] if valid else None), raw


def _rejected(block_id: str, raw: dict, body: str) -> RejectedBlock:
    kind = raw.get("type")
    if not isinstance(kind, str):
        found = _TYPE_IN_BROKEN_JSON.search(body)
        kind = found.group(1) if found else None
    return RejectedBlock(id=block_id, type=kind, raw=raw, text=body.strip())


def _json_object(body: str) -> dict:
    try:
        value = json.loads(body, parse_constant=_no_constants)
    except (ValueError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _no_constants(name: str):
    # NaN and Infinity parse in Python but are not JSON: a chart holding one
    # could not be sent to the reader.
    raise ValueError(name)


def _unusable(value, field: str | None = None) -> bool:
    """True when the JSON holds a value that would reach the reader wrong.

    A control character in a string is a LaTeX command written with one
    backslash (`\\text`, `\\frac`), which JSON reads as an escape: the
    formula would be silently wrong. A newline is allowed in ordinary text but
    not in a LaTeX field, where it is `\\neq` or `\\nu`. A number that is not
    finite (`1e999` parses to infinity) could not be drawn or sent as JSON,
    and a boolean is not a coordinate.
    """
    if isinstance(value, bool):
        return field in _COORDINATE_FIELDS
    if isinstance(value, str):
        newline_ok = field not in _MATH_FIELDS
        return any(ord(char) < 32 and not (char == "\n" and newline_ok) for char in value)
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(_unusable(v, key) for key, v in value.items())
    if isinstance(value, list):
        return any(_unusable(v, field) for v in value)
    return False


def _prepared(raw: dict, block_id: str, sources: dict[str, str]) -> dict:
    """The model's object with every server-owned field set or cleared."""
    data = {key: value for key, value in raw.items() if key not in _SERVER_FIELDS}
    data["id"] = block_id
    data["source_id"] = _source_id(raw.get("source"), sources)
    if isinstance(data.get("mistakes"), list):
        data["mistakes"] = [_without_evidence(mistake) for mistake in data["mistakes"]]
    return data


def _source_id(label, sources: dict[str, str]) -> str | None:
    if not isinstance(label, str):
        return None
    return sources.get(label.strip("[] ").upper())


def _without_evidence(mistake):
    """A mistake's `evidence` line is stamped by `verify` from the real quiz
    history, so whatever the model wrote there is dropped."""
    if not isinstance(mistake, dict):
        return mistake
    return {key: value for key, value in mistake.items() if key != "evidence"}


def _validated(entry: dict) -> list[Item]:
    valid, _ = parse_items([entry])
    return valid
