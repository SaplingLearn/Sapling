Create a new Architectural Decision Record (ADR) in `docs/decisions/` for the title in `$ARGUMENTS`.

Steps:

1. List `docs/decisions/`. Find the highest existing `NNNN-*.md` filename and use the next zero-padded 4-digit number. If none exist, start at `0001`. Ignore `.gitkeep` and any non-matching files.
2. Slugify `$ARGUMENTS`: lowercase, replace any run of non-alphanumeric characters with a single `-`, strip leading/trailing `-`.
3. Determine today's date in `YYYY-MM-DD` (use the `date` command: `date +%Y-%m-%d`).
4. Write the file at `docs/decisions/<NNNN>-<slug>.md` with this exact template (filling in `<NNNN>`, `<Title>` = `$ARGUMENTS` verbatim, and `<today's date>`):

```markdown
# <NNNN>: <Title>

- Status: proposed
- Date: <today's date, YYYY-MM-DD>
- Supersedes: none

## Context

<one paragraph>

## Decision

<one paragraph>

## Consequences

<bullet list, both positive and negative>
```

5. Print the relative path of the new file and remind the human to fill in the `Context`, `Decision`, and `Consequences` sections — leave the angle-bracket placeholders intact so it's obvious what's unwritten.

Do not commit. Do not modify any other file. Do not invent content for the placeholder sections.
