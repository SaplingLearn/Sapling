Search the dev-context vault for the query in `$ARGUMENTS` and return matching lines with context. Read-only.

Steps:

1. Check whether `rg` (ripgrep) is available: `command -v rg`. If yes, use `rg`. If not, fall back to `grep -rn -i -C 2`.
2. Search across exactly these paths, case-insensitive, with 2 lines of surrounding context:
   - `docs/decisions/`
   - `docs/attempts/`
   - `docs/architecture.md`
3. With `rg`, run: `rg -i -n -C 2 -- "$ARGUMENTS" docs/decisions/ docs/attempts/ docs/architecture.md`. With `grep` fallback: `grep -rn -i -C 2 -- "$ARGUMENTS" docs/decisions/ docs/attempts/ docs/architecture.md`.
4. Cap the output at the first 10 distinct match locations. For each match, show the file path, the line number, and the matching line plus its 2 lines of context (the default `-C 2` output is fine).
5. If there are zero matches, say so plainly with the exact query echoed back. Do **not** paraphrase, summarize, or invent any content from training data — only report what `rg`/`grep` actually found in the vault.

Do not modify any files. Do not read files outside the three search paths above.
