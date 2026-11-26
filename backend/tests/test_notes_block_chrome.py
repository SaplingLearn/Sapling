"""Generated blocks get their controls back.

A model writes a block's CONTENT reliably and its chrome unreliably. The
chrome is what makes the block usable: `library-notes.css` hides `.qa-a`
unless the block carries `data-open="1"`, and the only thing that flips that
is the `data-act="open"` button. A `qa` generated without one is an answer
that is written, saved, and permanently invisible — which is exactly what the
model produced on a real document on 2026-11-26.

The shapes asserted here are `frontend/src/lib/notes/blocks.ts`; the inputs
are the markup an actual generation run emitted.
"""
import pytest

from services.documents.doc_notes import fallback_notes, restore_block_chrome

# Verbatim from a real run against a cellular-respiration lecture.
GENERATED_QA = (
    '<div class="blk" data-blk="qa" data-open="0">'
    '<div class="qa-q">Q1. How many NADH does one glucose produce?</div>'
    '<div class="qa-a">Six, because the cycle turns twice.</div></div>'
)
GENERATED_TOGGLE = (
    '<div class="blk" data-blk="toggle" data-open="1">'
    '<div class="tg-head"><div class="tg-title">Worked Example</div></div>'
    '<div class="tg-body"><p>Count the carriers.</p></div></div>'
)
GENERATED_TABLE = (
    '<div class="blk" data-blk="table" data-edit="0"><table>'
    "<thead><tr><th>Carrier</th></tr></thead>"
    "<tbody><tr><td>NADH</td></tr></tbody></table></div>"
)


def test_qa_gains_the_button_that_reveals_its_answer():
    out = restore_block_chrome(GENERATED_QA)
    assert 'data-act="open"' in out
    assert "Show Answer" in out
    # The bar must sit BEFORE the answer, the way the editor's template does.
    assert out.index("Show Answer") < out.index('class="qa-a"')
    # The content is untouched.
    assert "Six, because the cycle turns twice." in out
    assert "Q1. How many NADH does one glucose produce?" in out


def test_qa_gains_its_label_and_remove_button():
    out = restore_block_chrome(GENERATED_QA)
    assert 'class="blk-x"' in out and 'data-act="del"' in out
    assert 'class="blk-h"' in out and "Practice Question" in out


def test_toggle_gains_the_arrow_that_collapses_it():
    out = restore_block_chrome(GENERATED_TOGGLE)
    assert 'class="tg-arrow"' in out and 'data-act="open"' in out
    # Inside the head, before the title — the arrow is the head's first child.
    head = out.index('class="tg-head"')
    assert head < out.index('class="tg-arrow"') < out.index('class="tg-title"')


def test_table_gains_its_edit_button_and_row_controls():
    out = restore_block_chrome(GENERATED_TABLE)
    assert 'data-act="tedit"' in out
    for act in ("row", "col", "delrow", "delcol"):
        assert f'data-act="{act}"' in out
    # The control bar follows the table, not precedes it.
    assert out.index("</table>") < out.index('data-act="row"')


@pytest.mark.parametrize(
    "html", [GENERATED_QA, GENERATED_TOGGLE, GENERATED_TABLE])
def test_restoring_twice_changes_nothing(html):
    once = restore_block_chrome(html)
    assert restore_block_chrome(once) == once


def test_every_block_in_one_document_is_repaired():
    doc = f"<h2>A</h2>{GENERATED_QA}<p>x</p>{GENERATED_TOGGLE}{GENERATED_QA}"
    out = restore_block_chrome(doc)
    assert out.count("Show Answer") == 2
    assert out.count('class="tg-arrow"') == 1
    assert "<h2>A</h2>" in out and "<p>x</p>" in out


def test_a_block_that_already_has_its_chrome_is_left_alone():
    complete = (
        '<div class="blk" data-blk="qa" data-open="0">'
        '<button class="blk-x" contenteditable="false" data-act="del" '
        'title="Remove" aria-label="Remove block">×</button>'
        '<div class="blk-h" contenteditable="false">Practice Question</div>'
        '<div class="qa-q">Q</div>'
        '<div class="tbl-bar" contenteditable="false">'
        '<button class="sbtn" data-act="open">Show Answer</button></div>'
        '<div class="qa-a">A</div></div>'
    )
    assert restore_block_chrome(complete) == complete


def test_content_with_no_blocks_is_returned_unchanged():
    plain = "<h2>Overview</h2><p>No blocks here.</p>"
    assert restore_block_chrome(plain) == plain


def test_an_unclosed_block_does_not_lose_content():
    out = restore_block_chrome('<div class="blk" data-blk="qa" data-open="0">'
                               '<div class="qa-a">A</div>')
    assert "A" in out


def test_the_fallback_checklist_is_tickable():
    """The no-model path writes the same checklist and needs the same box."""
    out = fallback_notes({"summary": "A short summary.", "file_name": "x.pdf"})
    assert 'class="box"' in out and 'data-act="check"' in out


def test_the_injected_chrome_matches_the_frontend_templates():
    """The chrome this module injects is the editor's own markup, copied.

    `restore_block_chrome` writes Python string constants that only mean
    something because `frontend/src/lib/notes/blocks.ts` builds the same
    shapes and `useNoteBlocks.ts` reads the same `data-act` values. Nothing
    links the two files, so a rename on the frontend would leave the backend
    quietly emitting dead buttons — the exact failure this module exists to
    stop. This pins them: every action the backend injects must be one the
    frontend's templates actually use.
    """
    import re
    from pathlib import Path

    from services.documents import doc_notes as dn

    blocks = (Path(__file__).resolve().parents[2]
              / "frontend/src/lib/notes/blocks.ts").read_text(encoding="utf-8")
    frontend_acts = set(re.findall(r'data-act="([^"]+)"', blocks))

    injected = "".join([dn._BLK_X, dn._QA_BAR, dn._TG_ARROW,
                        dn._TBL_EDIT, dn._TBL_BAR])
    backend_acts = set(re.findall(r'data-act="([^"]+)"', injected))

    assert backend_acts, "no actions injected — the constants moved or emptied"
    unknown = backend_acts - frontend_acts
    assert not unknown, (
        f"the backend injects {sorted(unknown)}, which blocks.ts no longer "
        "drives; a generated block carrying it would render a dead control"
    )

    # The classes the stylesheet hangs the controls on must exist too.
    for cls in ("blk-x", "tbl-bar", "sbtn", "tg-arrow", "tbl-edit"):
        assert f'class="{cls}' in blocks, \
            f"blocks.ts no longer uses .{cls}"
