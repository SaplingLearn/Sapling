# Rich notes content model — design

> Sub-project 1 of 4 in the Summary Editor's move toward a full editable-notes
> experience (toolbar/ToC, persistent comments, and a Study Guide merge follow
> in later specs/plans). This sub-project is the foundation the other three
> build on: it changes what a `summary_docs` document's *content* can be, not
> yet how a student edits or annotates it.

## 1. Problem

Two things are true about today's Summary Editor content and need fixing
together:

1. **The generated notes are thinner than intended.** `document_notes_agent`'s
   prompt already says "this is NOT a summary... cover every topic... do not
   truncate" — but the agent runs under `WORKER_LIMITS`
   (`total_tokens_limit=50_000`), a budget shared with cheap one-paragraph
   tasks (classification, the card-preview summary). Gemini 2.5 Flash's own
   single-response output ceiling is 65,536 tokens — *larger than the entire
   shared budget this task runs under*. For any real lecture-length source,
   input tokens alone can consume most of that 50k, silently truncating the
   "comprehensive" notes the prompt asks for. The prompt's intent and the
   budget it runs under are working against each other.

2. **The content model can't hold what useful notes need.** Every section's
   `body` is plain prose, paragraph-split on blank lines — no lists, no
   tables, no math notation. The reference screenshots the notes should move
   toward show nested outlines, comparison tables, and rendered math
   (`lim(x→a) f(x) = L`). Today's `prosemirror_doc_from_sections` can only
   emit paragraph and heading nodes.

Both halves matter: widening the content model without fixing the token
budget just gives the agent more *ways* to still produce something short.

## 2. Content flow

```
documents.extracted_text
        │
        ▼
document_notes_agent (NOTES_LIMITS, not WORKER_LIMITS)
        │  ComprehensiveNotes { sections: [NotesSection, ...] }
        │  NotesSection.body: str (prose + "- "/"1. " lines + $..$/$$..$$ spans)
        │  NotesSection.table: TableBlock | None (structured, not parsed)
        ▼
prosemirror_doc_from_sections()
        │  per section: heading node, then body_to_prosemirror_nodes(body),
        │  then table_to_prosemirror_node(table) if present
        ▼
summary_docs.content (JSONB, encrypted) ──► SummaryEditor.tsx renders it
```

The same `body_to_prosemirror_nodes`/`table_to_prosemirror_node` pair is
reused on the suggestion ("ask") path:

```
create_suggestion() → summary_edit_agent → proposed_text: str (same dialect)
        │
        ▼ (on every read: creation response AND get_summary_doc's
        │  pending_suggestions list — never persisted)
        proposed_content: dict  (ProseMirror JSON, built from proposed_text)
        ▼
SummaryEditor.tsx's keepSuggestion() inserts proposed_content via
insertContentAt(range, proposed_content) — not the raw string.
```

And the reverse direction — the agent reading a document that already has
tables/math in it — goes through `plaintext_from_prosemirror`, extended to
render those node types back to legible text (table → tab/pipe-delimited
rows, math node → its LaTeX source) so an "ask" about existing rich content
has something coherent to reason about.

## 3. Data model

**Backend (Pydantic, `agents/document_notes.py`):**

```python
class TableBlock(BaseModel):
    """A single table. Flat, not parsed from text — eliminates the single
    highest-ambiguity part of letting an LLM emit tabular data (column
    alignment, missing separator rows) by never asking it to express a
    table as text in the first place."""
    headers: list[str]
    rows: list[list[str]]


class NotesSection(BaseModel):
    heading: str
    heading_level: int
    body: str = Field(
        description=(
            "Prose paragraphs (blank-line separated), optionally containing "
            "\"- \" / \"1. \" list lines and inline ($...$) or block ($$...$$) "
            "math spans. No other markdown syntax, no HTML, no fenced "
            "code blocks."
        ),
    )
    table: TableBlock | None = Field(
        default=None,
        description=(
            "A structured table for this section, when the material is "
            "naturally tabular (a comparison, a list of named facts). Give "
            "the section a dedicated heading when it is primarily a table; "
            "do not also restate the table's content as prose in body."
        ),
    )


class ComprehensiveNotes(BaseModel):
    sections: list[NotesSection] = Field(min_length=1)
```

Still flat — `table` is a sibling field on the existing section shape, not a
new level of nesting, so the structured-output budget concern that kept
`NotesSection` flat in the first place still holds.

**No new database columns or tables.** `summary_docs.content` stays the same
JSONB column; it just holds a wider vocabulary of ProseMirror node types.
`summary_doc_suggestions.proposed_text` stays the sole encrypted-at-rest
column for a suggestion's content — `proposed_content` is computed at read
boundaries, never persisted, so no new column carries the same content
unencrypted alongside the existing encrypted one.

## 4. Backend

**`agents/document_notes.py`:**
- `TableBlock` + `NotesSection.table` as above.
- System prompt extended: use a table when comparing multiple items or
  listing structured facts; use `$...$`/`$$...$$` for any mathematical
  expression rather than describing it in prose; use list lines for
  enumerable steps or criteria; write currency/plain numeric amounts in
  words ("25 dollars") rather than a bare `$` sign, so `$` only ever appears
  as a math delimiter. Framed as "use these when they make the notes more
  useful to study from," not "always use every feature."
- New `NOTES_LIMITS` usage-limits object (own module or alongside
  `WORKER_LIMITS` in `agents/__init__.py`): `total_tokens_limit=300_000`,
  same `request_limit=3`/`tool_calls_limit=0` shape as `WORKER_LIMITS`.
  300k comfortably covers a long source document's input plus genuinely
  thorough output while staying well short of unbounded cost/latency.
  `agents/document.py`'s `_step_notes` passes `usage_limits=NOTES_LIMITS`
  instead of `WORKER_LIMITS`.
- `_PROMPT_HASH` recomputes automatically from the prompt change, as it
  already does — no separate update needed, but the hash value changes.

**`services/summary_docs_service.py`:**
- New `body_to_prosemirror_nodes(body: str) -> list[dict]`: splits on blank
  lines into blocks; each block is classified as a list (every non-empty
  line starts with `- ` or `N. `) or a paragraph; within a paragraph block,
  `$...$`/`$$...$$` spans become inline math nodes, everything else becomes
  a text node. No general markdown — no headings, links, emphasis, or HTML
  recognized inside `body` (those don't belong in body text at all; headings
  come from the section's own `heading`/`heading_level` fields).
- New `table_to_prosemirror_node(table: TableBlock) -> dict`: direct
  structural conversion, no parsing — `table`/`tableRow`/`tableCell`/
  `tableHeader` nodes from `headers`/`rows`.
- `prosemirror_doc_from_sections`: per section, after the heading node, call
  `body_to_prosemirror_nodes` then append `table_to_prosemirror_node` if
  `section.table` is set.
- `plaintext_from_prosemirror`: extended to walk `table` nodes (render as
  tab-separated rows) and the new math node type (render its `latex`
  attribute, wrapped in `$...$` or `$$...$$` matching whether it was inline
  or block), in addition to the paragraph/heading walking it already does.
- `create_suggestion`: after building `proposed_text` as today, also compute
  `proposed_content = body_to_prosemirror_nodes(proposed_text)` (plus a table
  node if the agent's structured output included one — `summary_edit_agent`'s
  own output type gains the same optional `table: TableBlock | None` field
  `NotesSection` has, for symmetry) and include it in the returned dict.
  Never passed to `table("summary_doc_suggestions").insert(...)`.
- `get_summary_doc`: for each row in `pending_suggestions`, compute the same
  `proposed_content` after decryption, before returning — the Keep flow works
  identically whether the suggestion was just created or fetched on a later
  page load.

## 5. Frontend

**New dependencies:** `@tiptap/extension-table`,
`@tiptap/extension-table-row`, `@tiptap/extension-table-cell`,
`@tiptap/extension-table-header`, `@tiptap/extension-underline`,
`@tiptap/extension-highlight`, `katex`.

**`SummaryEditor.tsx`:** extensions list widens to include the table set,
Underline, Highlight, and the new math node (below). No other change to this
file in this sub-project — the split-pane/reference work from the prior
sub-project is untouched.

**New `MathNode` (TipTap Node + NodeView), likely
`frontend/src/lib/summaryEditor/mathNode.ts`:**
- Inline atom node, one attribute: `latex: string`.
- NodeView renders via `katex.renderToString(latex, { throwOnError: false })`
  into the node's DOM — a real rendered formula, not raw `$...$` text.
- Click/double-click opens a small popup (a plain positioned `<input>`, not a
  new modal system) pre-filled with the raw LaTeX; committing updates the
  node's `latex` attribute and re-renders. `throwOnError: false` means
  malformed LaTeX renders KaTeX's own inline error markup rather than
  crashing the editor.
- `keepSuggestion`'s `insertContentAt` already accepts ProseMirror JSON
  fragments (TipTap's command API takes JSON or a string), so inserting a
  `proposed_content` fragment containing a math/table node works with the
  existing Keep code path, no new insertion logic needed there.

**`keepSuggestion` (existing function in `SummaryEditor.tsx`):** switches
from inserting `s.proposed_text` (a string) to inserting `s.proposed_content`
(the ProseMirror JSON fragment) at both call sites (anchored and whole-doc).
`SummaryDocSuggestion` (frontend type) gains `proposed_content: unknown`
(typed as the JSON-node-array shape TipTap's `insertContentAt` accepts).

## 6. Security

- `body_to_prosemirror_nodes` recognizes exactly three constructs — blank-line
  paragraphs, `- `/`N. ` list lines, `$...$`/`$$...$$` math spans — and
  nothing else. No raw HTML passthrough, no link/image syntax, no fenced code
  blocks. This is a deliberate choice over adopting a general markdown
  library (e.g. `markdown-it`): source-document text is already treated as
  untrusted elsewhere in this codebase (`wrap_untrusted`/`neutralize_delimiters`
  in the ask-prompt building), and a general markdown parser supporting raw
  HTML passthrough would reopen a stored-XSS-shaped path from source-document
  content flowing into notes body text. A narrow, fully-enumerated converter
  closes that off by construction rather than by configuration.
- `table`/`proposed_content` carry no new encryption surface:
  `proposed_content` is derived from the already-decrypted `proposed_text` at
  the point of use and never written to a column of its own (see §3) — no new
  plaintext-at-rest column is introduced.
- KaTeX's `throwOnError: false` is itself a small security/robustness choice
  — malformed LaTeX (whether AI-generated or, later, student-edited) degrades
  to an inline error span rather than throwing inside a render path.

## 7. Error handling

- `body_to_prosemirror_nodes`: an unclosed `$`/`$$` span (no matching closing
  delimiter before the next blank line) is not treated as math — the whole
  span, delimiters included, is emitted as literal text. A line starting with
  `- `/`N. ` that's the only line in its block is still a valid one-item list
  (no minimum length).
- `table_to_prosemirror_node`: a row with a different cell count than
  `headers` is padded with empty cells (short row) or truncated (long row) —
  never raises. An empty `rows` list still renders a table with just the
  header row.
- Agent-side: `document_notes_agent` keeps its existing `retries=2`
  output-validation budget — the new fields are additive and optional
  (`table` defaults to `None`), so this doesn't change the agent's failure
  modes, only what a successful output can contain.

## 8. Explicitly out of scope (this sub-project)

- Toolbar UI to apply underline/highlight/insert-table manually (sub-project
  2 — "Formatting toolbar + ToC").
- Collapsible/foldable sections (sub-project 2).
- Table of contents, live or static-in-document (sub-project 2 supersedes
  today's static synthetic ToC block in `prosemirror_doc_from_sections`,
  which this sub-project leaves untouched).
- Persistent, pinned comments (sub-project 3).
- The Study Guide → `summary_docs` merge (sub-project 4).
- WYSIWYG math editing — only raw-LaTeX-source editing via the popup.
- Backfilling existing `summary_docs` rows into the richer schema — forward-
  only; old documents keep rendering fine under the widened TipTap schema,
  they just won't retroactively gain tables/math/lists.
- Circling/highlighting the *source* PDF/text producing tables or math in a
  reference — the source-reference-viewer's existing text/image reference
  flow (built in the prior session) is untouched by this spec.

## 9. Key decisions (for future reference)

- **Tables are a structured field, not parsed text.** The single highest-risk
  part of "let the LLM write markdown" is column-aligned pipe tables — easy
  for a model to get subtly wrong (missing separator row, inconsistent cell
  counts) and hard for a parser to recover from gracefully. Making `table` a
  flat, optional, directly-typed field sidesteps that risk entirely rather
  than mitigating it with better parsing.
- **One converter, not two.** The frontend never parses the markdown-lite
  dialect itself. `proposed_content` is always server-computed, so the
  suggestion/Keep path and the initial-seed path share exactly one
  implementation of "text dialect → ProseMirror nodes" — considered and
  rejected a parallel TypeScript parser (duplication risk for no benefit,
  since the frontend needs to consume server-built JSON for tables either
  way).
- **Math is a node, not a mark.** A TipTap mark can only restyle existing
  text; it cannot replace what's rendered. Real KaTeX glyph rendering
  requires a NodeView, which only nodes have.
- **The token-budget fix belongs here, not in a separate cleanup.** Widening
  the content model without also fixing `WORKER_LIMITS` → `NOTES_LIMITS`
  would ship the *capability* for comprehensive, well-structured notes while
  leaving the actual generation silently bottlenecked below the model's own
  single-response output ceiling — the same root problem the content-model
  work is meant to fix, just moved one layer down.
