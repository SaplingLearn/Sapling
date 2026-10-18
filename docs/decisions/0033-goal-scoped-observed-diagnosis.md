# 0033 — Confirmed goals and observed diagnostic boundaries

Date: 2026-10-18
Status: Accepted for PR #673; production launch gates remain unchanged.

## Context

Posterior stabilization could end an all-correct check-in without observing a
ceiling. The planner did not constrain concepts to a student's goal. A bounded
question bank cannot establish an exact or universal frontier of understanding.

## Decision

- Use BKT only to select an initial challenge. Adapt from explicitly independent
  observations: escalate after success, descend after failure, bisect between
  observed bounds, and retest contradictory difficulty levels. Give unfinished
  strands fair coverage. A boundary requires minimum independent evidence and an
  ordered correct floor below an incorrect/explicit-unknown ceiling.
- Preserve finite session, per-strand and novice fatigue stops. Distinguish a
  bracketed result from partial, inconsistent, above/below available range and
  untested results. Show missing goal prerequisites, including beyond the three
  selected strands. Bank shortages and caps are limits, not proof of a boundary.
- Help, prior item exposure, release rechecks and synthetic refusal-to-unknown
  fallback cannot certify an independent boundary. Capture the final help floor
  immediately before the existing evidence write. Legacy history has unknown
  help provenance; keep its fatigue counts without treating it as independent.
- Let students confirm one to twelve owned course concept targets and optional
  objective text. Do not silently map prose to concepts. Constrain all plan
  candidates, reviews and siblings to those targets' complete prerequisite
  closure. An independently failed concept remains a planning need despite an
  older high posterior. This local priority does not fabricate mastery evidence.
- Encrypt objective text within `sessions.loop_state.goal.text_encrypted`;
  expose it only after session ownership checks and wrap it as untrusted tutor
  context. IDs and diagnosis metadata contain no learner prose. Do not log goals.
- Before teaching, allow goal edits that preserve graded history, presentation
  limits and evidence. Version goals; reject precomputed probe/plan writes and
  approvals after a goal change. Exclude grading/closing and atomically require
  `ended_at IS NULL AND close_json IS NULL` on goal writes. Once teaching starts,
  changing a goal requires a new session.
- Page course graph and prerequisite reads, and batch learner-state IDs, so a
  PostgREST row limit cannot silently turn missing prerequisites into roots.

## Consequences

The student sees what was tested and why a prerequisite appears in their plan.
The frontend supports goal editing, resume and conflict recovery on desktop and
narrow mobile screens. Existing coursewide exploration and legacy sessions remain
valid. A new session starts coursewide unless a goal is explicitly supplied.

Difficulty levels and cut-points remain engineering heuristics; three assessed
strands and finite available questions can leave a broad goal incomplete. This
change establishes observable implementation behavior, not calibrated measurement
or demonstrated student retention/transfer. No production promotion is authorized.
