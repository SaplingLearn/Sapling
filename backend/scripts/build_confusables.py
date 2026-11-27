"""Generate learning/_confusables.py from Unicode's UTS #39 confusables.txt (spec §13 A33).

    cd backend && venv/bin/python scripts/build_confusables.py [path/to/confusables.txt]

Without a path the pinned file is fetched from unicode.org. The file must be the
pinned version, byte for byte (SOURCE_SHA256), and this interpreter's
`unicodedata` must be the same Unicode version: the skeleton's NFD and the
character names below come from it. Offline ops only — never imported by
application code.

What the answer guard needs is not the raw skeleton. UTS #39 compares two
strings by mapping both to a "skeleton", and its prototypes are not always the
letter a reader sees: `m` → `rn`, `I` → `l`, `1` → `l`, `0` → `O`, `"` → `''`.
The guard's rules are ASCII regexes over a detection copy of the student's text,
so the table maps only NON-ASCII characters, each to the ASCII text whose own
skeleton equals its skeleton (`г` → `r`, `Ꮢ` → `R`, `“` → `"`, `ο` → `o`).
ASCII is never rewritten (`r1` stays `r1`, never `rl`). Where several ASCII
characters share a skeleton (`l`, `I`, `1`, `|`), the source's own category
picks one (an upper-case letter → `I`, a lower-case one → `l`, a digit → `1`).

UTS #39 does not list every Latin look-alike: `ɾ` (r with fishhook) and most
Latin small capitals (`ʀ`, `ᴀ`, `ᴛ`) are absent in 15.1.0 and 16.0.0. The same
Unicode version's character names close that gap without a hand list: a
`LATIN … LETTER X WITH …` (a letter with a hook, stroke, tail or other
attachment) and a Latin small capital X map to X. A skeleton that lands on one
of them resolves through it (`н` → `ʜ` → `h`, `ꭱ` → `ʀ` → `r`). A character
whose skeleton has no ASCII reading (`—` → `ー`, `м` → `ʍ`) is left out.
Characters NFKD already decomposes (fullwidth, mathematical alphanumerics) are
left out too: the guard folds with NFKD before it reads this table.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

UNICODE_VERSION = "15.1.0"
SOURCE_URL = f"https://www.unicode.org/Public/security/{UNICODE_VERSION}/confusables.txt"
SOURCE_SHA256 = "8289f833e4cf78fde56b2080dc0e42934ef5182c9c3f4dd1fbdf2bced69fd5ed"
OUT = Path(__file__).resolve().parents[1] / "learning" / "_confusables.py"

_ASCII_PRINTABLE = [chr(cp) for cp in range(0x21, 0x7F)]
_NAMED_LATIN = re.compile(
    r"LATIN (?:(?P<case>SMALL|CAPITAL) LETTER|LETTER SMALL CAPITAL|SMALL CAPITAL LETTER) "
    r"(?P<letter>[A-Z])(?: WITH .+)?"
)
_MARKS = frozenset({"Mn", "Me"})


def parse(text: str) -> dict[str, str]:
    """confusables.txt → {source character: prototype sequence}."""
    table: dict[str, str] = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        source, target, _kind = (field.strip() for field in line.split(";"))
        table[chr(int(source, 16))] = "".join(chr(int(cp, 16)) for cp in target.split())
    return table


def named_latin() -> dict[str, str]:
    """Non-ASCII Latin letters with an attachment, and Latin small capitals, by name."""
    out: dict[str, str] = {}
    for cp in range(0x80, sys.maxunicode + 1):
        m = _NAMED_LATIN.fullmatch(unicodedata.name(chr(cp), ""))
        if m:
            letter = m["letter"]
            out[chr(cp)] = letter if m["case"] == "CAPITAL" else letter.lower()
    return out


def _skeleton(text: str, table: dict[str, str]) -> str:
    """UTS #39 skeleton (NFD, prototype mapping, NFD) with combining marks dropped,
    as the guard's fold drops them."""
    mapped = "".join(table.get(c, c) for c in unicodedata.normalize("NFD", text))
    return "".join(
        c for c in unicodedata.normalize("NFD", mapped) if unicodedata.category(c) not in _MARKS
    )


def _pick(candidates: list[str], source: str) -> str:
    """The ASCII character a source reads as, when several share its skeleton."""
    category = unicodedata.category(source)
    if category == "Lu":
        order = (str.isupper, str.islower, str.isdigit)
    elif category.startswith("L"):
        order = (str.islower, str.isupper, str.isdigit)
    elif category.startswith("N"):
        order = (str.isdigit, str.isupper, str.islower)
    else:
        order = (lambda c: not c.isalnum(),)
    return min(candidates, key=lambda c: ([not test(c) for test in order], c))


def build(confusables_text: str) -> dict[str, str]:
    """{non-ASCII character: its ASCII reading} — see the module docstring."""
    table = parse(confusables_text)
    named = named_latin()
    by_skeleton: dict[str, list[str]] = {}
    for c in _ASCII_PRINTABLE:
        by_skeleton.setdefault(_skeleton(c, table), []).append(c)
    units = sorted(by_skeleton, key=len, reverse=True)

    def ascii_reading(target: str, source: str) -> str | None:
        out, i = [], 0
        while i < len(target):
            unit = next((u for u in units if target.startswith(u, i)), None)
            if unit is not None:
                out.append(_pick(by_skeleton[unit], source))
                i += len(unit)
            elif target[i] in named:
                out.append(named[target[i]])
                i += 1
            else:
                return None
        return "".join(out) or None

    result: dict[str, str] = {}
    for source in sorted(set(table) | set(named)):
        if source.isascii() or unicodedata.normalize("NFKD", source) != source:
            continue
        reading = ascii_reading(_skeleton(source, table), source) if source in table else None
        reading = reading or named.get(source)
        if reading and reading != source:
            result[source] = reading
    return result


def table_sha256(table: dict[str, str]) -> str:
    """The checksum tests pin: one `<HEX> <reading>` line per source, sorted."""
    lines = "".join(f"{ord(s):04X} {d}\n" for s, d in sorted(table.items()))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def _escape(text: str) -> str:
    return "".join(
        c
        if c.isascii() and c.isalnum()
        else f"\\u{ord(c):04x}"
        if ord(c) <= 0xFFFF
        else f"\\U{ord(c):08x}"
        for c in text
    )


def render(table: dict[str, str]) -> str:
    """The data module: sources grouped by their ASCII reading, all escaped."""
    by_reading: dict[str, list[str]] = {}
    for source, reading in sorted(table.items()):
        by_reading.setdefault(reading, []).append(source)
    rows = "\n".join(
        f'    "{_escape(reading)}": "{_escape("".join(sources))}",'
        for reading, sources in sorted(by_reading.items())
    )
    return f'''"""GENERATED by scripts/build_confusables.py from Unicode {UNICODE_VERSION} — never edit by hand.

Non-ASCII characters that read as ASCII, for learning/answer_guard's detection
copy (spec §13 A33): the UTS #39 confusables ({SOURCE_URL},
sha256 {SOURCE_SHA256}) resolved to the ASCII text sharing each
character's skeleton, plus Latin letters with an attachment and Latin small
capitals by character name. No imports, no I/O.
"""

UNICODE_VERSION = "{UNICODE_VERSION}"
SOURCE_SHA256 = "{SOURCE_SHA256}"
#: scripts/build_confusables.table_sha256(CONFUSABLES)
TABLE_SHA256 = "{table_sha256(table)}"

# ASCII reading -> every source character that reads as it.
_BY_READING = {{
{rows}
}}

#: {{source character: ASCII reading}}
CONFUSABLES = {{source: reading for reading, sources in _BY_READING.items() for source in sources}}
'''


def main(argv: list[str]) -> int:
    if unicodedata.unidata_version != UNICODE_VERSION:
        print(
            f"unicodedata is Unicode {unicodedata.unidata_version}; this table pins "
            f"{UNICODE_VERSION}. Run it under a Python whose unicodedata matches.",
            file=sys.stderr,
        )
        return 2
    if argv:
        raw = Path(argv[0]).read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL) as response:  # noqa: S310 - pinned https URL
            raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        print(f"confusables.txt sha256 {digest} is not the pinned {SOURCE_SHA256}", file=sys.stderr)
        return 2
    text = raw.decode("utf-8-sig")
    if f"# Version: {UNICODE_VERSION}" not in text:
        print(f"confusables.txt does not say Version: {UNICODE_VERSION}", file=sys.stderr)
        return 2
    table = build(text)
    OUT.write_text(render(table), encoding="utf-8")
    print(f"wrote {OUT.name}: {len(table)} characters, table sha256 {table_sha256(table)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
