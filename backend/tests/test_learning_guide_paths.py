"""The learning-loop engineer's guide (docs/learning-loop/*.md) names real code.

The guide is only useful while the paths and names it cites exist, so this
test fails CI when the code moves under it. The extraction rule is simple on
purpose — keep it that way, and write the guide to it:

1. Fenced code blocks (``` ... ```) are skipped: they hold diagrams and
   shell commands, not references.
2. Every other inline code span (`...`) whose text starts with a repo top-level
   directory in ``ROOTS`` (``backend/``, ``frontend/``, ``docs/`` ...) is a PATH
   REFERENCE, resolved against the repository root. A trailing ``/`` means a
   directory; a ``*`` makes it a glob that must match at least one file; a
   ``#fragment`` is ignored.
3. ``path::name`` also names a symbol. In a ``.py`` file the name must be
   DEFINED at module level (a ``def``, ``class`` or assignment, including inside
   a module-level ``if``/``try``) — an import does not count; ``Class.member``
   looks inside the class. In any other file the name must appear as a whole
   word (an SQL function, a TS export, a Makefile target).
4. Line numbers rot, so ``path:123`` is rejected: cite ``path::name`` instead.
5. Relative Markdown links (``[text](other.md)``, ``[text](../x/y.md#part)``)
   must point at an existing file or directory.

Spans that do not start with a root (``apply_graph_update``, ``LOOP_TIER``,
``python -m pytest``) are prose and are not checked.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

REPO = Path(__file__).resolve().parents[2]
GUIDE = REPO / "docs" / "learning-loop"

#: The pages the guide promises (README.md links to each).
PAGES = (
    "README.md",
    "architecture.md",
    "flows.md",
    "data-model.md",
    "invariants.md",
    "operations.md",
    "amendments.md",
    "glossary.md",
    "contributing.md",
)

#: Repo top-level directories a path reference may start with.
ROOTS = ("backend/", "frontend/", "docs/", "scripts/", "supabase/", "specs/", ".github/")

#: A guide with fewer references than this means the extraction broke, not
#: that the guide stopped citing code (it cited about 675 when this was set).
MIN_REFERENCES = 300

_FENCE = re.compile(r"^(```|~~~)")
_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^)\s]+)\)")
_LINE_NUMBER = re.compile(r":\d+(?:[-–]\d+)?$")


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """The lines outside fenced code blocks, with their 1-based numbers."""
    out, fenced = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line.lstrip()):
            fenced = not fenced
            continue
        if not fenced:
            out.append((n, line))
    return out


def _references(page: Path) -> list[tuple[str, int, str]]:
    """(page name, line, span) for every path reference on a page."""
    refs = []
    for n, line in _prose_lines(page.read_text(encoding="utf-8")):
        for span in _SPAN.findall(line):
            span = span.strip()
            if span.startswith(ROOTS):
                refs.append((page.name, n, span))
    return refs


def _links(page: Path) -> list[tuple[str, int, str]]:
    links = []
    for n, line in _prose_lines(page.read_text(encoding="utf-8")):
        for target in _LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue  # http(s):, mailto:, in-page anchors
            links.append((page.name, n, target))
    return links


def _defined(path: Path, dotted: str) -> bool:
    """Is `dotted` (``name`` or ``Class.member``) defined in this Python file?"""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    parts = dotted.split(".")
    for i, part in enumerate(parts):
        found = None
        queue = list(body)
        while queue and found is None:
            node = queue.pop(0)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == part:
                    found = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
                if part in names:
                    found = node
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                queue.extend(node.body)
                queue.extend(getattr(node, "orelse", []))
                queue.extend(getattr(node, "finalbody", []))
                for handler in getattr(node, "handlers", []):
                    queue.extend(handler.body)
        if found is None:
            return False
        if i < len(parts) - 1:
            if not isinstance(found, ast.ClassDef):
                return False
            body = found.body
    return True


def _problem(span: str) -> str | None:
    """None when the reference resolves; else what is wrong with it."""
    if _LINE_NUMBER.search(span.split("::")[0]):
        return "line numbers rot: cite path::name instead"
    path_text, _, symbol = span.partition("::")
    path_text = path_text.split("#", 1)[0]
    if "*" in path_text:
        return None if list(REPO.glob(path_text)) else "glob matches no file"
    path = REPO / path_text
    if path_text.endswith("/"):
        return None if path.is_dir() else "no such directory"
    if not path.exists():
        return "no such file"
    if not symbol:
        return None
    if path.suffix == ".py":
        return None if _defined(path, symbol) else f"`{symbol}` is not defined in {path_text}"
    text = path.read_text(encoding="utf-8")
    word = r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])"
    return None if re.search(word, text) else f"`{symbol}` does not appear in {path_text}"


def _all(fn) -> list[tuple[str, int, str]]:
    out = []
    for page in sorted(GUIDE.glob("*.md")):
        out.extend(fn(page))
    return out


def test_every_page_exists():
    missing = [p for p in PAGES if not (GUIDE / p).is_file()]
    assert not missing, f"docs/learning-loop/ is missing {missing}"


def test_the_extraction_finds_the_guides_references():
    refs = _all(_references)
    assert len(refs) >= MIN_REFERENCES, (
        f"only {len(refs)} path references found — did the extraction rule break?"
    )


def test_every_path_reference_resolves():
    bad = []
    for page, line, span in _all(_references):
        problem = _problem(span)
        if problem:
            bad.append(f"{page}:{line}: `{span}` — {problem}")
    assert not bad, "the guide cites code that does not exist:\n" + "\n".join(bad)


def test_every_relative_link_resolves():
    bad = []
    for page, line, target in _all(_links):
        path = (GUIDE / unquote(target.split("#", 1)[0])).resolve()
        if not path.exists():
            bad.append(f"{page}:{line}: ({target})")
    assert not bad, "the guide links to missing files:\n" + "\n".join(bad)


@pytest.mark.parametrize(
    "span, ok",
    [
        ("backend/learning/bkt.py", True),
        ("backend/learning/bkt.py::update", True),
        ("backend/learning/bkt.py::no_such_function", False),
        ("backend/learning/", True),
        ("backend/db/migrations/*_learning_*.sql", True),
        ("backend/learning/bkt.py:12", False),
        ("backend/no/such/file.py", False),
    ],
)
def test_the_rule_itself(span, ok):
    """The checker accepts real references and rejects broken ones."""
    assert (_problem(span) is None) is ok
