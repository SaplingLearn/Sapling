Record something that was tried and didn't work, in `docs/attempts/`. The slug for the attempt is in `$ARGUMENTS`.

Steps:

1. Determine today's date in `YYYY-MM-DD` (use `date +%Y-%m-%d`).
2. Slugify `$ARGUMENTS`: lowercase, replace any run of non-alphanumeric characters with a single `-`, strip leading/trailing `-`. Treat the slugified value as `<slug>`.
3. Derive a human title from the slug: replace `-` with spaces and capitalize the first letter of each word. That's `<Title from slug>`.
4. Write the file at `docs/attempts/<YYYY-MM-DD>-<slug>.md` with this exact template:

```markdown
# <Title from slug>

- Date: <YYYY-MM-DD>
- Related: <link to ADR or file if relevant, otherwise "none">

## What I tried

## Why it didn't work

## What I'd try next
```

5. Print the relative path and remind the human:
   - The `What I'd try next` section is **mandatory** — never leave it blank when filling in the file.
   - Fill in `Related` with a path to a relevant ADR (`docs/decisions/NNNN-*.md`) or source file if applicable; otherwise the literal string `none`.

Do not commit. Do not invent content for the body sections — leave them empty for the human to write.
