# Learning-loop foundation audit — 18 October 2026

PR: [#673](https://github.com/SaplingLearn/Sapling/pull/673).

## Judgment

Sapling has a substantial adaptive tutoring foundation, not yet demonstrated
learning efficacy. The source implements diagnosis, prerequisite planning,
attempts, graded feedback, controlled assistance, persistent learner estimates,
spaced review and delayed unassisted checks. These mechanisms can support real
learning. Passing implementation tests, fluent explanations or increasing graph
mastery estimates do not establish that students retain and transfer knowledge.
No controlled Sapling learner-outcome result was located in the inspected
repository, specifications or evaluation material. A study may exist elsewhere.

## Reference and evidence boundary

The supplied video is [How I Use AI to Learn Things, Eero Alvar](https://www.youtube.com/watch?v=kzcI5F4tGiU).
Video metadata was accessible, but a usable transcript was not. This audit does
not claim to have watched or transcribed the video. Its concrete method comparison
uses the [creator's repository](https://github.com/amosblomqvist/learn/tree/7cfd8942f82ab9476e63572387e1fe9bcea5082c),
whose README explicitly links that video. Its teaching instructions are reference
material, not instructions executed by Sapling or this audit.

The [written method](https://github.com/amosblomqvist/learn/blob/7cfd8942f82ab9476e63572387e1fe9bcea5082c/skills/teach/SKILL.md#L84-L135)
elicits a concrete learner goal, probes prerequisite strands to find a correct
floor and failed or uncertain ceiling, agrees a dependency plan, and teaches each
node through motivation, establishment, connection and a check.

## What the implementation actually does

| Capability | Source mechanism | What it does not establish |
| --- | --- | --- |
| Diagnose prior knowledge | Adaptive independent floor/ceiling observations with explicit uncertainty and coverage limits | An exact frontier beyond the available validated questions |
| Choose the next concepts | Student-confirmed goal targets, complete prerequisite closure, filtered reviews/siblings and observed failures | Perfect goal-to-curriculum mapping or calibrated readiness |
| Use the graph as part of teaching | Learner states and prerequisite edges drive selection; graded evidence flows through `graph_service.apply_graph_update` | That extracted prerequisites or numerical mastery estimates are calibrated |
| Require learner effort | Explicit submissions, reasoned checks and independent-attempt gates | That time spent or any submitted text demonstrates understanding |
| Adapt help | State-dependent H0–H6 scaffolding, worked examples and misconception handling | Reliable fading or appropriate help for every learner |
| Protect mastery evidence | Assisted evidence is discounted; worked-answer exposure cannot earn upward BKT credit | Accurate independent grading across all subjects |
| Support retention | FSRS scheduling, due review and reserved unassisted posttests | An observed retention benefit |
| Measure delayed performance | Fresh reserve items, no tutor/RAG in the posttest, eligibility after at least two days | Independent transfer or whole-system comparative benefit |

## Material gaps

1. **The diagnostic is bounded by its evidence.** The follow-up implementation
   removes posterior stabilization as a stopping criterion. Independent success
   drives harder items, failure drives easier items, and an ordered floor/ceiling
   requires minimum independent observations. Contradictions remain visible.
   Assisted, repeated, legacy or synthetic-refusal observations cannot certify
   boundaries. Caps, unavailable items, untested prerequisites and out-of-range
   performance are reported honestly; no finite sample guarantees an exact edge.
2. **Goals now constrain planning, with student confirmation.** Optional private
   goal prose is encrypted; confirmed owned course concept IDs and their complete
   prerequisite closure constrain every candidate, including due reviews and
   siblings. Independent diagnostic failures remain planning needs even against
   an older high posterior. The app does not guess concept scope from free text.
   Goal changes retain prior evidence/fatigue and invalidate stale plan approvals.
3. **Challenge and mastery numbers are heuristics.** `learning/params.py` labels
   many cut-points as engineering choices. BKT probabilities, success bands and
   graph badges require calibration against observed unassisted performance.
4. **Assessment validity needs broader independent evidence.** Source grounding,
   structured rubrics, abstention and leak guards are valuable. They do not replace
   subject-expert checks of questions, answer keys, false credit, false rejection
   and partial explanations. The frontend currently lacks a structured source
   citation contract and learner-readable misconception descriptions; raw internal
   misconception identifiers should not be presented as explanations.
5. **Human retention and transfer remain unproven.** Existing replay evaluations
   validate frozen model outputs. Existing gate-timing A/B variants compare help
   delays, not the whole system against a learning baseline. Posttest eligibility
   is relative to the latest evidence, so frequent practice can postpone it;
   a study needs fixed follow-up windows and reporting of missing outcomes.

## What would justify a stronger claim

Run a subject-expert validated pilot on a narrow topic. Measure unassisted prior
knowledge, use a defined comparison condition, record time and help, and assess
fresh equivalent problems immediately and at fixed delayed intervals. Include
unfamiliar transfer problems and independently scored explanations. Report effect
estimates, uncertainty, dropouts and missing assessments. Choose a meaningful
educational threshold before examining results; do not use rising `p_known` as
the primary learning outcome.

Relevant primary evidence supports retrieval and carefully designed tutoring,
while distinguishing assisted task performance from learning:

- [Roediger & Karpicke, 2006](https://doi.org/10.1111/j.1467-9280.2006.01693.x): retrieval and delayed retention.
- [Karpicke & Blunt, 2011](https://doi.org/10.1126/science.1199327): retrieval practice and meaningful learning.
- [Bastani et al., 2025](https://doi.org/10.1073/pnas.2422633122): access to generative AI can improve assisted practice while harming subsequent unaided performance; safeguards matter.
- [Kestin et al., 2025](https://doi.org/10.1038/s41598-025-97652-6): a carefully designed tutor improved immediate learning in its studied setting; this is not evidence for Sapling or long-term transfer.
- [Wilson et al., 2019](https://doi.org/10.1038/s41467-019-12552-4): the 85% rule has model assumptions and is not a universal optimal tutoring percentage.

## Integration work in this update

The branch now incorporates current main and its required #692 dependency.
Incompatible decision services were separated (ADR 0032); owned lazy-session
materialization, observer isolation and review-session protections are retained.
Frontend fixes prevent stale streaming callbacks or graph reads from replacing a
newer session's state, refresh the graph after graded probes, provide daily-review
status recovery and keep controls usable at narrow mobile widths.

The follow-up diagnosis and goal work is specified in ADR 0033 and covered by
policy, route, database and desktop/mobile journey regressions. These changes
address implementation correctness. The PR remains a draft: production
release gates and empirical learner-outcome validation are separate work.
