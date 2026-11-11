# HANDOFF-NN — <slug>

Written by the session that executed `PKG-NN-<slug>.md`. Read by every later package that depends on NN. Keep every heading, even if the answer is "none".

## What changed

Three to eight sentences. Present tense. What is true now that was not true before.

## Symbols added

One per line, `path::name` with a one-line contract. Include new tables, columns, event types, AgentTask literals, function-mode handler names, routes, frontend exports.

## Constants chosen

`NAME = value` with the spec §3 reference. Mark `†` on any value that is an engineering choice without a validated cut-point (the spec lists them). If a value differs from the spec, it is a Deviation below, not a silent change.

## Deviations from spec

`<spec said> → <did instead> → <why>`. Same lines appended to `LEDGER.md` Deviations.

## Known gaps

What this package deliberately left undone that a later package or a human must pick up. Flakes observed (spec name, count, whether it passes in isolation).

## Verify commands

Copyable. Each line: command → expected output. These lines become the next package's "State of the world" rows verbatim.

```
cd backend && venv/bin/python -m pytest tests/test_learning_<x>.py -q   → N passed
grep -n "^def <symbol>" backend/learning/<module>.py                     → 1 hit
```

## Open questions for the series owner

Decisions the session could not make from the spec. Each with the option it took in the meantime.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
