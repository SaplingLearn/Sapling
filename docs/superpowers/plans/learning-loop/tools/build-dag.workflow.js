// Claude Code Workflow script that built learning-loop PKG-04..06b, A37 (see CONTINUE.md §5).
// Run with the Workflow tool: args = { repo, scratch, integration_worktree, e2e_env?, packages: [{num, slug, file, after:[...], extra?, resume?, decision?, lane?, branch?}] }
export const meta = {
  name: 'learning-loop-build-dag4',
  description: 'Build learning-loop PKG-04..14 in dependency order in lane worktrees: implement, 3-lens verify, fix, E2E gate on the local stack, merge into PR #673 branch and push',
  whenToUse: 'Executing the remaining learning-loop PKG prompts with per-package integration into feat/learning-loop',
  phases: [
    { title: 'Implement', detail: 'one agent per package executes its PKG prompt in its own lane worktree' },
    { title: 'Verify', detail: 'conformance, regression, adversarial-correctness verifiers (read-only)' },
    { title: 'Fix', detail: 'fixer confirms findings and fixes them test-first' },
    { title: 'E2E', detail: 'serialized local-stack cycle (Playwright + oracles) per package' },
    { title: 'Integrate', detail: 'serialized merge into feat/learning-loop, full checks, push to PR #673' },
    { title: 'Launch check', detail: 'final fresh-DB E2E on the PR branch, both lanes' },
  ],
}

const MAIN = args.repo  // the main checkout, e.g. /home/you/Sapling
const SP = args.scratch  // a scratch folder for lane worktrees
const PR_WT = args.integration_worktree  // a worktree with feat/learning-loop checked out
const ENVSH = args.e2e_env || (MAIN + '/docs/superpowers/plans/learning-loop/tools/e2e-env.macos.sh')
const INT = 'feat/learning-loop'
const FULL_SUITE = 'cd backend && venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py'
const TRAILER = 'Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>'

const lane = p => p.lane || (SP + '/lanes/pkg-' + p.num)
const branchOf = p => p.branch || ('feat/learning-loop-' + p.num + '-' + p.slug)

function mutex() {
  let tail = Promise.resolve()
  return fn => { const run = tail.then(fn, fn); tail = run.then(() => {}, () => {}); return run }
}
const e2eLock = mutex()
const intLock = mutex()

const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['done', 'blocked'] },
    branch: { type: 'string' },
    head_sha: { type: 'string' },
    tests_added: { type: 'integer' },
    full_suite: { type: 'string' },
    ruff: { type: 'string' },
    frontend_checks: { type: 'string' },
    e2e: { type: 'string', description: 'e2e_cycle results you ran yourself, or "not run"' },
    acceptance: { type: 'array', items: { type: 'object', properties: { criterion: { type: 'string' }, passed: { type: 'boolean' }, output: { type: 'string' } }, required: ['criterion', 'passed'] } },
    deviations: { type: 'array', items: { type: 'string' } },
    deferred: { type: 'array', items: { type: 'string' } },
    notes: { type: 'string' },
  },
  required: ['status', 'branch', 'head_sha', 'full_suite', 'acceptance', 'deviations', 'deferred'],
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['critical', 'major', 'minor'] }, file: { type: 'string' }, line: { type: 'integer' },
      description: { type: 'string' }, evidence: { type: 'string' }, suggested_fix: { type: 'string' } },
      required: ['severity', 'description', 'evidence'] } },
    checks_run: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
  required: ['issues', 'checks_run', 'summary'],
}
const FIX_SCHEMA = {
  type: 'object',
  properties: {
    fixed: { type: 'array', items: { type: 'string' } },
    rejected: { type: 'array', items: { type: 'object', properties: { issue: { type: 'string' }, reason: { type: 'string' } }, required: ['issue', 'reason'] } },
    head_sha: { type: 'string' }, full_suite: { type: 'string' }, ruff: { type: 'string' },
  },
  required: ['fixed', 'rejected', 'head_sha', 'full_suite'],
}
const E2E_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['green', 'red', 'infra-error'] },
    lanes: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, playwright: { type: 'string' }, oracles: { type: 'string' }, log: { type: 'string' } }, required: ['name', 'playwright', 'oracles'] } },
    failures: { type: 'array', items: { type: 'object', properties: { spec: { type: 'string' }, first_error: { type: 'string' }, classification: { type: 'string', enum: ['regression', 'pre-existing', 'flaky', 'infra'] }, evidence: { type: 'string' } }, required: ['spec', 'first_error', 'classification'] } },
    migrations: { type: 'string' },
    summary: { type: 'string' },
  },
  required: ['status', 'lanes', 'failures', 'summary'],
}
const INT_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['integrated', 'failed'] },
    merge_sha: { type: 'string' }, head_sha: { type: 'string' },
    full_suite: { type: 'string' }, frontend_checks: { type: 'string' },
    pushed: { type: 'boolean' }, conflicts: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' },
  },
  required: ['status', 'head_sha', 'full_suite', 'pushed'],
}

const STACK_RULES = `LOCAL E2E STACK (machine singleton): \`source ${ENVSH}\` then \`e2e_cycle <worktree_dir> [playwright args]\` runs ONE whole cycle (make e2e-up → playwright → e2e_oracles → make e2e-down) inside the machine lock; set \`E2E_FRESH_DB=1\` to replay every migration from an empty DB (always do this when the branch adds a migration). A warm cycle takes ~4.5 min, and it may first wait up to 90 min for the lock while another lane holds it — ALWAYS run it with the Bash tool's run_in_background and wait for the completion notification (or poll its log with short commands); never run make e2e-up / e2e-down / supabase start outside e2e_cycle, never run make explore. Extra env for a lane (e.g. LEARNING_LOOP_ENABLED=false for a kill-switch lane) is exported before calling e2e_cycle. Known pre-existing flake on this Mac: e2e/gradebook.spec.ts:35 (Landing.tsx term-chip race) — not a regression unless the diff touches Landing/gradebook. The backend runs in function mode in the lane (SAPLING_MODEL_MODE=function, agents.function_handlers_e2e).`

const OVERRIDES = p => `SESSION OVERRIDES (these beat the prompt file and the README):
1. Worktree + branch. You work ONLY in the lane worktree ${lane(p)} on branch ${branchOf(p)}. Set it up first if missing:
   mkdir -p ${SP}/lanes && git -C ${MAIN} worktree add -b ${branchOf(p)} ${lane(p)} ${INT}   (if the branch already exists: git -C ${MAIN} worktree add ${lane(p)} ${branchOf(p)})
   then in the lane: ln -sfn ${MAIN}/backend/venv backend/venv; ln -sfn ${MAIN}/backend/.env backend/.env; cp -cR ${PR_WT}/frontend/node_modules frontend/node_modules (APFS clone; if you change frontend/package-lock.json, run npm ci instead with node 22: source ~/.nvm/nvm.sh && nvm use 22). Never edit ${MAIN} or ${PR_WT} or another lane. The branch is cut from ${INT} (PR #673's branch), which already contains every earlier package merged and verified. Where the prompt says "branch from main" or "open a PR", read "${INT}" and "PR #673".
2. Never git push, never gh pr create, never merge into another branch, never rebase. The pipeline's integrator merges your branch into ${INT} after review and E2E. Skip the prompt's PR task; your last step is the hand-off + ledger commit.
3. Every commit message ends with exactly: ${TRAILER}
4. Tests. backend deps = CI lockfile set in backend/venv (Python 3.13); the OCR stack is not installed, so the full suite is ALWAYS: ${FULL_SUITE} — it must end with 0 failures. Run targeted tests + tests/test_learning_loop_invariants.py + \`cd backend && venv/bin/ruff check .\` after every task, the full suite after any task that edits a pre-existing non-series file and once at the end. Frontend changes: \`cd frontend && source ~/.nvm/nvm.sh && nvm use 22 && npm run typecheck && npm run lint && npm test\`.
5. Secrets. backend/.env holds LOCAL values incl. a real GEMINI_API_KEY. Never print, echo, copy or commit any .env value; never git add a .env file or the venv/node_modules links; before every commit \`git diff --cached | grep -cE "AIza[S]y|GOC[S]PX"\` must print 0. Stage explicit paths only.
6. ${STACK_RULES} Run a cycle whenever your prompt's self-check requires one (request-path route/agent touched, migrations, E2E specs) and while developing Playwright specs; the pipeline ALSO runs an E2E gate after review, so a cycle you cannot get green for reasons outside your diff is reported, not hidden.
7. Evals — only if this package adds or changes an agent prompt or tool description: record cassettes for THIS package's dataset only (SAPLING_EVAL_MODE=record, ≤ 8 cases, real GEMINI_API_KEY from backend/.env), replay, then refresh baselines for that dataset only (SAPLING_EVAL_UPDATE_BASELINES=1). Never re-record another dataset. If recording fails for a reason outside your code (quota, network), keep the dataset module + evaluator unit tests, leave it out of run_all.py/baselines.json and record it as deferred.
8. Precedence when sources disagree: spec §13 Amendments (every row, A1 onward) > the actual symbols in earlier HANDOFF-*.md files and the code on disk > the prompt text. Adapt names to what earlier packages actually shipped and record each adaptation as a Deviation. Ledger: a package's state is its LATEST row; "verified" or "done" or "reopened" as the latest row all count as satisfied.
9. Scope: change only files in this package's Files lists, plus LEDGER.md, HANDOFF-${p.num}.md, and earlier-package reopens done exactly per the README protocol.
10. Blocked after 3 honest iterations on one task: follow "If you get stuck", commit what is green, report status "blocked".${p.extra ? '\n\nPACKAGE-SPECIFIC OVERRIDES:\n' + p.extra : ''}`

const implPrompt = p => `You are executing one package of the Sapling learning-loop implementation series. Your instructions are the prompt file docs/superpowers/plans/learning-loop/${p.file} (read it inside your lane worktree after setting it up). Read it completely, then everything it lists under "Read before you start" (LEDGER.md, the spec incl. its §13 Amendments log and §14 order, earlier HANDOFF files, the code anchors). Run its "State of the world" checks first; a red row means repair per the prompt's rule (on your branch) before building. Then execute every task in order, test-first, exactly as written, subject to these overrides.

${OVERRIDES(p)}

When finished, return the structured result: status, branch, head SHA (git rev-parse HEAD in the lane), tests added, the exact summary line of your final full-suite run, ruff result, frontend check results if any, any E2E cycles you ran with results, every acceptance criterion from the prompt with pass/fail and output, deviations, deferred items.`

const LENSES = [
  { key: 'conformance', text: (p, br) => `LENS: CONFORMANCE TO THE PROMPT AND SPEC. Read docs/superpowers/plans/learning-loop/${p.file} and the spec docs/superpowers/specs/2026-09-26-learning-loop-design.md (§3, §4, §5, §7, §8, §11, §13, §14). Check the implementation on ${br} (diff base: merge-base with ${INT}): every task's deliverables exist with the specified names/signatures (or a documented Deviation); named constants match the spec/§13 value and live in backend/learning/params.py (no stray numeric literals in loop code); migrations match spec §4 DDL + §13, named <14 digits>_learning_<desc>.sql; run EVERY acceptance-criteria command in the prompt except E2E-stack ones and compare with the expected output; HANDOFF-${p.num}.md has every template heading and its Verify block equals the prompt's canonical block; LEDGER.md has this package's row; commits end with the trailer "${TRAILER}"; nothing pushed.` },
  { key: 'regression', text: (p, br) => `LENS: REGRESSION, SCOPE, SAFETY. On ${br}: run the full suite (${FULL_SUITE}) — 0 failures, report the summary line; \`cd backend && venv/bin/ruff check .\`; the invariants module; if frontend/ changed: \`cd frontend && source ~/.nvm/nvm.sh && nvm use 22 && npm run typecheck && npm run lint && npm test\`. Scope: \`git diff --stat $(git merge-base ${INT} HEAD)..HEAD\` — every path in the prompt's Files lists, LEDGER/HANDOFF, or a documented reopen. Dark-launch safety (all packages before PKG-14 half B): with LEARNING_LOOP_ENABLED unset every pre-existing code path is byte-identical — no new DB read, no behaviour change, no new UI visible to students; flag tests that claim this but would pass if it were broken. Secrets: \`git log -p $(git merge-base ${INT} HEAD)..HEAD | grep -cE "AIza[S]y|GOC[S]PX"\` = 0 and no tracked .env. No pre-existing test deleted, skipped or xfailed without the prompt requiring it.` },
  { key: 'correctness', text: (p, br) => `LENS: ADVERSARIAL CORRECTNESS. Read the full diff \`git diff $(git merge-base ${INT} HEAD)..HEAD\` on ${br} and the spec sections it implements. Hunt real defects: wrong maths vs the spec (verify numerically with backend/venv python when relevant), boundary/off-by-one at thresholds, wrong defaults, swallowed exceptions hiding failures, async misuse, shared mutable state across requests, encryption boundaries (encrypted column filtered/compared, plaintext stored), privacy/consent leaks (student text to a new vendor, class rollups below n), the single-writer rule (graph/mastery/learner_state written outside apply_graph_update), answer-leak and prompt-injection paths, budget caps that create or bias evidence, cost regressions (a Pro call where the spec routes to Flash/lite, missing max_tokens/thinking caps), and tests that pass without exercising what they name. Give concrete evidence (failing input with actual vs expected, or the quoted line and why). No style nits; omit anything you cannot substantiate.` },
]

const verifyPrompt = (p, br, lens, round, previous) => `You are a READ-ONLY verifier for PKG-${p.num} (${p.slug}) of the Sapling learning-loop series. Work in the lane worktree ${lane(p)} (branch ${br}). Do not edit, stage, commit, checkout, stash or reset anything. Never print .env values. Do NOT run the E2E stack — the pipeline's E2E gate runs it after review, so "E2E not run yet" is not an issue.
${round > 0 ? `Re-verification round ${round}. Confirm each earlier finding below is resolved and look for regressions the fixes introduced:\n${JSON.stringify(previous, null, 1)}\n` : ''}
${lens.text(p, br)}
${p.decision ? `\nCOORDINATOR DECISIONS (settled by the series coordinator — verify they are implemented correctly and completely, but do NOT re-open the design itself; a residual the decision explicitly accepts and that HANDOFF documents with tests is not an issue):\n${p.decision}\n` : ''}
Severity: critical = wrong behaviour, data/privacy/security risk, or broken build/tests; major = spec or acceptance criterion not met, or a real bug with limited blast radius; minor = small gap without behavioural impact. Return issues (empty if none), checks run, and a one-paragraph summary.`

const fixPrompt = (p, br, issues, source) => `You are the fixer for PKG-${p.num} (${p.slug}) of the Sapling learning-loop series, in the lane worktree ${lane(p)} on branch ${br}. ${source} reported the findings below. For EACH: reproduce/confirm it against the code, docs/superpowers/plans/learning-loop/${p.file} and the spec (§13 wins). If real, fix it test-first (a failing test that reproduces it, then the fix) and commit as \`fix(learning-loop): PKG-${p.num} — <what>\` ending with \`${TRAILER}\`. If not real, reject it with a concrete reason. Fix every confirmed critical/major; fix minor ones when cheap and safe. Update HANDOFF-${p.num}.md if a fix changes something recorded there.
Rules: never push/PR/merge; never print or commit .env values (\`git diff --cached | grep -cE "AIza[S]y|GOC[S]PX"\` = 0 before each commit); stay in scope except a documented reopen. ${STACK_RULES}
After fixing: ruff, invariants, the full suite (${FULL_SUITE}); frontend checks if frontend changed. Report the exact suite summary line.

FINDINGS:
${JSON.stringify(issues, null, 1)}`

const e2ePrompt = (p, br, attempt) => `You run the E2E gate for PKG-${p.num} (${p.slug}) on the lane worktree ${lane(p)} (branch ${br}). Read-only on the repo: do not edit tracked files, do not commit.
${STACK_RULES}
Steps: ensure frontend/node_modules exists in the lane (cp -cR ${PR_WT}/frontend/node_modules frontend/node_modules if missing; npm ci with node 22 if frontend/package-lock.json differs from ${PR_WT}'s). Read docs/superpowers/plans/learning-loop/${p.file} for any package-specific E2E lanes (e.g. the loop lane vs the kill-switch lane, extra env vars, specific specs) and spec §11.4. Run the default lane first: \`source ${ENVSH}; E2E_FRESH_DB=1 e2e_cycle ${lane(p)}\` (background + wait). Then each extra lane the prompt defines, one cycle each. For every failing spec, re-run just that spec once (\`e2e_cycle ${lane(p)} <spec> --repeat-each 2\`) to separate flakes; if you suspect it is pre-existing, run that spec on the integration worktree ${PR_WT} too (read-only there as well). Classify each failure: regression (caused by this branch), pre-existing (fails on ${INT} too), flaky (passes on re-run), infra. Also report whether this branch's migrations applied (grep the cycle log for "Applied N migration(s)" and the new filenames). status: green = no regression and oracles exit 0 with 0 findings; red = any regression or oracle finding caused by the branch; infra-error = the stack could not run. Attempt ${attempt}.`

const intPrompt = (p, br, e2e) => `You are the integrator. Merge ${br} (PKG-${p.num} ${p.slug}, reviewed and E2E-gated) into ${INT} in the integration worktree ${PR_WT}, verify, and push so PR #673 updates. Work only in ${PR_WT}; never touch ${MAIN} or other lanes' files.
1. \`cd ${PR_WT} && git status --short\` must be clean (else stop: failed). \`git merge --no-ff --no-commit ${br}\`.
2. Conflicts: LEDGER.md / HANDOFF-*.md / README.md → ordered union keeping every row and line (rows already on ${INT} first, then the branch's new rows). Code conflicts (params.py, events taxonomy, agents/_providers.py, agents/function_handlers_e2e.py, routes/learn_loop.py, tests, frontend files) → keep both sides' additions; never drop a test or an assertion; re-read both packages' HANDOFFs if unsure.
3. Checks on the merged tree: \`cd backend && venv/bin/ruff check .\`, the invariants module, the full suite (${FULL_SUITE}) → 0 failures. If frontend/ changed since the merge base: \`cd frontend && source ~/.nvm/nvm.sh && nvm use 22 && npm run typecheck && npm run lint && npm test\` (if node_modules is stale vs package-lock.json, npm ci first).
4. A failure caused by the interaction of the merge: fix it minimally, test-first, in a follow-up commit \`fix(learning-loop): PKG-${p.num} — <what> after merging into ${INT}\`. If it cannot be fixed safely, \`git merge --abort\` (or reset to the pre-merge commit you recorded) and return status failed with details.
5. Commit the merge with a normal-English message: subject "Merge PKG-${p.num} ${p.slug} into the learning-loop PR branch", a short body saying what the package delivers and the check results, ending with ${TRAILER}.
6. Append one LEDGER.md row after the last table row: \`| ${p.num} | ${p.slug} | verified | ${INT} | <merge sha> | — | Series <UTC date>: merged; full suite <summary line>; E2E gate: ${(e2e && e2e.summary ? e2e.summary : 'see HANDOFF').replace(/\|/g, '/').slice(0, 300)} | HANDOFF-${p.num}.md |\` and commit it as \`docs(learning-loop): PKG-${p.num} verified on the PR branch\` (+ trailer).
7. Secret checks: \`git log -p origin/${INT}..HEAD | grep -cE "AIza[S]y|GOC[S]PX"\` = 0 and \`git ls-files | grep -E "(^|/)\\.env$"\` empty — else stop, do not push.
8. \`git push origin ${INT}\` — never --force, never any other branch. If rejected because the remote moved, \`git pull --no-rebase origin ${INT}\`, re-run the targeted tests, push again.
Return status, merge sha, final head sha, full-suite line, frontend checks, pushed, conflicts resolved (paths), notes.`

async function verifyLoop(p, br) {
  let round = 0, previous = []
  const history = []
  while (true) {
    const verdicts = await parallel(LENSES.map(l => () => agent(verifyPrompt(p, br, l, round, previous), {
      label: `verify ${p.num} ${l.key}${round ? ' r' + round : ''}`, phase: 'Verify', schema: VERIFY_SCHEMA })))
    const issues = verdicts.filter(Boolean).flatMap(v => v.issues || [])
    const blocking = issues.filter(i => i.severity !== 'minor')
    history.push({ round, issues: issues.length, blocking: blocking.length })
    log(`PKG-${p.num} verify r${round}: ${issues.length} findings (${blocking.length} critical/major)`)
    if (!issues.length) return { ok: true, history }
    if (round >= 2) return { ok: !blocking.length, history, open: blocking }
    const fix = await agent(fixPrompt(p, br, issues, 'Verifiers'), { label: `fix ${p.num} r${round + 1}`, phase: 'Fix', schema: FIX_SCHEMA })
    history.push({ fix_round: round + 1, fixed: fix ? fix.fixed.length : null, rejected: fix ? fix.rejected.length : null, suite: fix ? fix.full_suite : null })
    if (!blocking.length) return { ok: true, history }
    previous = blocking
    round++
  }
}

async function e2eGate(p, br) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    const r = await e2eLock(() => agent(e2ePrompt(p, br, attempt), { label: `e2e ${p.num} #${attempt}`, phase: 'E2E', schema: E2E_SCHEMA }))
    if (!r) return { status: 'infra-error', summary: 'e2e agent failed' }
    log(`PKG-${p.num} E2E #${attempt}: ${r.status} — ${r.summary.slice(0, 160)}`)
    if (r.status === 'green') return r
    if (r.status === 'infra-error' && attempt >= 2) return r
    const regressions = (r.failures || []).filter(f => f.classification === 'regression')
    if (r.status === 'red' && regressions.length && attempt < 3) {
      await agent(fixPrompt(p, br, r.failures, 'The E2E gate (Playwright journeys + e2e_oracles on the local stack)'), { label: `fix ${p.num} e2e#${attempt}`, phase: 'Fix', schema: FIX_SCHEMA })
    } else if (r.status === 'red' && !regressions.length) {
      return { ...r, status: 'green', summary: r.summary + ' (no regression: failures pre-existing/flaky)' }
    }
  }
  return { status: 'red', summary: 'E2E still red after 3 attempts' }
}

const decisionPrompt = p => `You are the fixer for PKG-${p.num} (${p.slug}) of the Sapling learning-loop series, in the lane worktree ${lane(p)} on branch ${branchOf(p)} (already implemented and reviewed; review found the blocking issues below). The series coordinator has made the DESIGN DECISION below to end an oscillation between two fix rounds; implement it exactly, test-first, as \`fix(learning-loop): PKG-${p.num} — <what>\` commits ending with \`${TRAILER}\`. Record the decision as a Deviation in HANDOFF-${p.num}.md and LEDGER.md Deviations, and rewrite any Known gap it changes so it states the real remaining behaviour.
Rules: never push/PR/merge; never print or commit .env values (\`git diff --cached | grep -cE "AIza[S]y|GOC[S]PX"\` = 0 before each commit); stay in scope. After fixing: ruff, invariants, the full suite (${FULL_SUITE}); report the exact summary line.

${p.decision}`

async function build(p) {
  log(`PKG-${p.num} ${p.slug}: start${p.resume ? ' (resumed)' : ''}`)
  let impl
  if (p.resume) {
    impl = { status: 'done', branch: branchOf(p), full_suite: 'resumed from an earlier run', acceptance: [], deviations: [], deferred: [] }
    if (p.decision) {
      const fx = await agent(decisionPrompt(p), { label: `decide+fix ${p.num}`, phase: 'Fix', schema: FIX_SCHEMA })
      if (!fx) return { pkg: p.num, status: 'agent-failed' }
      log(`PKG-${p.num} decision fix: ${fx.fixed.length} fixed, ${fx.rejected.length} rejected; ${fx.full_suite}`)
    }
  } else {
    impl = await agent(implPrompt(p), { label: `implement ${p.num} ${p.slug}`, phase: 'Implement', schema: IMPL_SCHEMA })
  }
  if (!impl) return { pkg: p.num, status: 'agent-failed' }
  if (impl.status !== 'done') return { pkg: p.num, status: 'blocked', impl }
  const br = impl.branch || branchOf(p)
  const v = await verifyLoop(p, br)
  if (!v.ok) return { pkg: p.num, status: 'unresolved', impl, verify: v }
  const e2e = await e2eGate(p, br)
  if (e2e.status !== 'green') return { pkg: p.num, status: 'e2e-' + e2e.status, impl, verify: v, e2e }
  const integ = await intLock(() => agent(intPrompt(p, br, e2e), { label: `integrate ${p.num}`, phase: 'Integrate', schema: INT_SCHEMA }))
  if (!integ || integ.status !== 'integrated') return { pkg: p.num, status: 'integration-failed', impl, verify: v, e2e, integ }
  log(`PKG-${p.num}: integrated ${integ.head_sha} pushed=${integ.pushed}`)
  return { pkg: p.num, status: 'integrated', branch: br, impl_suite: impl.full_suite, acceptance_failed: (impl.acceptance || []).filter(a => !a.passed).map(a => a.criterion), deviations: impl.deviations, deferred: impl.deferred, verify: v.history, e2e: e2e.summary, integ }
}

const pkgs = args.packages
const byNum = {}
for (const p of pkgs) byNum[p.num] = p
const running = {}
function schedule(num) {
  if (!running[num]) {
    const p = byNum[num]
    running[num] = (async () => {
      const deps = await Promise.all((p.after || []).map(schedule))
      const bad = deps.filter(d => !d || d.status !== 'integrated')
      if (bad.length) { log(`PKG-${num}: skipped (dependency ${bad.map(b => b ? b.pkg + ':' + b.status : '?').join(', ')})`); return { pkg: num, status: 'skipped' } }
      try { return await build(p) } catch (e) { return { pkg: num, status: 'error', error: String(e) } }
    })()
  }
  return running[num]
}
const results = await Promise.all(pkgs.map(p => schedule(p.num)))

let launch = null
if (results.every(r => r.status === 'integrated')) {
  launch = await e2eLock(() => agent(`Final launch verification of PR #673 (branch ${INT}) in the integration worktree ${PR_WT}. Read-only on tracked files; do not commit or push. ${STACK_RULES}
1. Read spec §11.1, §11.3, §11.4 and docs/superpowers/plans/learning-loop/HANDOFF-14.md to learn the E2E lanes the launched system must pass (the default lane where the loop is every student's default, and the kill-switch lane with LEARNING_LOOP_ENABLED=false).
2. Run each lane with E2E_FRESH_DB=1 on ${PR_WT} (one e2e_cycle per lane, background + wait). Re-run any failing spec once in isolation to separate flakes.
3. On the default lane, confirm from the Playwright output that the learn-loop journeys (probe → plan → teach → check → close, resume, budget cap) passed, and that the Learn and Study screens show the loop UI for a student with no opt-in.
4. Run the full backend suite (${FULL_SUITE}) and the frontend checks (cd frontend; nvm use 22; npm run typecheck && npm run lint && npm test).
Return lanes with results, failures with classification, the suite line, frontend results, and a one-paragraph verdict: is the learning loop working as the default learning system end to end on the local stack, and what the owner must still do (spec §11.7 runbook steps that need staging/production).`, { label: 'launch check', phase: 'Launch check', schema: E2E_SCHEMA }))
}
return { results, launch }