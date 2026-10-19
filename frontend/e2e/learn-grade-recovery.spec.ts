/** Durable grade recovery through the real browser/API/atomic evidence writer.
 *
 * A test-process-only Python fault interrupts actual IDK grading immediately
 * before its evidence flush. It persists the app's authenticated encrypted
 * checkpoint; it never fabricates a grade, receipt, posterior or journal row.
 * The worker then exits. Browser recovery uses the normal running backend,
 * whose empty retry body must preserve that original frozen IDK outcome.
 * Only newly created synthetic question assets are withdrawn after the fault.
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { Browser, Page } from "@playwright/test";

import { expect, killSwitchLane, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { decryptText } from "./support/decrypt";
import { LOOP_STREAM_CAPTURE_SCRIPT, loopStreamCompleted, markLoopStream, readLoopStream } from "./support/loop-streams";
import { mintStorageState } from "./support/session";
import { USER_LOOP } from "./support/stack";

type Kind = "check" | "probe";
type Fixture = { kind: Kind; session_id: string; node_id: string; question_hash: string;
  item_id: string; operation_id: string; grader_calls: number; withdrawn: boolean };
type Entry = { grading_claim?: string; grade_checkpoint?: string; graded?: number;
  graded_operation_id?: string; last_correct?: boolean; last_verdict?: string };
type State = { phase: string; current?: string | null; goal?: unknown; goal_version?: number;
  checks_since_rating?: number; steps?: Record<string, Entry>;
  probe?: { current?: Entry | null; history?: Array<{ grade_operation_id: string; idk: boolean; correct: boolean }> } };

// This helper runs only inside this spec, against the same guarded local stack
// as resetDb/decryptText. No fault switch or environment bypass enters production.
const PY_HOLD_GRADE = String.raw`
import json, os, sys, uuid
from urllib.parse import urlsplit
from unittest.mock import AsyncMock, patch
from dotenv import load_dotenv
load_dotenv()
if (os.getenv('APP_ENV') not in {'local', 'test'}
    or urlsplit(os.getenv('SUPABASE_URL', '')).hostname not in {'127.0.0.1', 'localhost', '::1'}):
    raise RuntimeError('Grade recovery fixture requires a local/test loopback database')
os.environ['SAPLING_MODEL_MODE'] = 'function'
os.environ['SAPLING_FUNCTION_HANDLERS'] = 'agents.function_handlers_e2e'
os.environ['LOGFIRE_TOKEN'] = ''
from fastapi.testclient import TestClient
from db.connection import table
from learning import grade_checkpoint
from learning.checks import question_hash
from learning.evidence import PlanningPersistenceUnavailable
from main import app
from routes import learn_loop
from services.check_item_service import concept_key
from services.encryption import decrypt_if_present, encrypt_if_present
from services.session_tokens import mint_session
payload = json.load(sys.stdin)
kind, token = payload['kind'], payload['token']
user, course, offering = 'rich-user-loop', 'rich-course-cs101', 'rich-off-cs101-s26'
node, session = str(uuid.uuid4()), str(uuid.uuid4())
name = 'Synthetic checkpoint browser fixture ' + token
table('graph_nodes').insert({'id': node, 'user_id': user, 'course_id': course, 'concept_name': name})
template = table('check_items').select('*', filters={'id': 'eq.rich-check-binary-free-d1'}, limit=1)[0]
synthetic_ids = set()
for variant in range(6):
    item = {key: value for key, value in template.items() if key != 'created_at'}
    prompt = decrypt_if_present(template['prompt']) + ' [checkpoint fixture ' + token + ':' + str(variant) + ']'
    item_id = 'e2e-checkpoint-' + token + '-' + str(variant)
    synthetic_ids.add(item_id)
    item.update(id=item_id, concept_key=concept_key(name), prompt=encrypt_if_present(prompt),
                question_hash=question_hash(prompt), graded=False)
    table('check_items').insert(item)
state = ({'phase': 'teach', 'plan': {'approved': [node], 'cursor': 0}, 'concept': node,
          'teach_turns': 0, 'concept_checks': 0} if kind == 'check' else {'phase': 'probe'})
table('sessions').insert({'id': session, 'user_id': user, 'offering_id': offering,
    'mode': 'socratic', 'topic': 'Synthetic durable grade recovery', 'loop_state': state, 'loop_state_rev': 0})
client = TestClient(app)
client.cookies.set('sapling_session', mint_session(user))
base = {'session_id': session, 'user_id': user}
def require(response, status, stage):
    if response.status_code != status:
        raise RuntimeError('Checkpoint fixture ' + stage + ' HTTP ' + str(response.status_code))
if kind == 'probe':
    response = client.post('/api/learn/loop/goal', json={**base,
        'goal': {'text': 'Recover this synthetic browser goal', 'target_node_ids': [node]}})
    require(response, 200, 'goal')
response = client.post('/api/learn/loop/' + ('check/next' if kind == 'check' else 'probe/next'), json=base)
require(response, 200, 'pose')
pose = response.json()['check'] if kind == 'check' else response.json()
qh = pose['question_hash']
posed_item = table('check_items').select('id', filters={'question_hash': 'eq.' + qh}, limit=1)[0]['id']
if posed_item not in synthetic_ids:
    raise RuntimeError('Checkpoint fixture must pose its own synthetic asset')
def interrupted(*args, **kwargs):
    raise PlanningPersistenceUnavailable('Synthetic interruption before evidence commit')
grade = AsyncMock(wraps=learn_loop.grade_answer)
with patch.object(learn_loop, 'grade_answer', grade), patch.object(learn_loop, 'flush_pending', interrupted):
    response = client.post('/api/learn/loop/' + ('check/answer' if kind == 'check' else 'probe/answer'),
        json={**base, 'question_hash': qh, 'idk': True, 'answer': payload['original_answer']})
require(response, 503, 'interrupted grade')
if grade.await_count != 1:
    raise RuntimeError('Checkpoint fixture must grade exactly once')
raw = table('sessions').select('loop_state', filters={'id': 'eq.' + session}, limit=1)[0]['loop_state']
entry = raw['steps'][qh] if kind == 'check' else raw['probe']['current']
saved = grade_checkpoint.open_checkpoint(entry[grade_checkpoint.KEY], kind=kind,
    operation_id=entry['grading_claim'], user_id=user, session_id=session, course_id=course, question_hash=qh)
if len(saved.evidence) != 1 or saved.evidence[0]['idk'] is not True or saved.evidence[0]['correct'] is not False:
    raise RuntimeError('Checkpoint fixture must preserve its actual IDK outcome')
if payload['original_answer'] in json.dumps(raw):
    raise RuntimeError('Checkpoint answer is not encrypted at rest')
# Withdraw only the selected newly authored fixture item, never a shared seed.
if payload['withdraw']:
    table('check_items').delete(filters={'id': 'eq.' + posed_item})
sys.stdout.write('\nCHECKPOINT_METADATA=' + json.dumps({'kind': kind, 'session_id': session,
    'node_id': node, 'question_hash': qh, 'item_id': posed_item,
    'operation_id': saved.operation_id, 'grader_calls': grade.await_count, 'withdrawn': payload['withdraw']}) + '\n')
`;

async function holdGrade(kind: Kind, originalAnswer: string): Promise<Fixture> {
  const backend = path.resolve(__dirname, "..", "..", "backend");
  const python = process.env.E2E_SEED_PYTHON?.trim() || path.join(backend, "venv", "bin", "python");
  return new Promise((resolve, reject) => {
    const child = spawn(python, ["-c", PY_HOLD_GRADE], { cwd: backend, timeout: 45_000 });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code !== 0) { reject(new Error(`Checkpoint fixture failed (${code}): ${stderr}`)); return; }
      const lines = stdout.split("\n").filter((line) => line.startsWith("CHECKPOINT_METADATA="));
      if (lines.length !== 1) { reject(new Error("Checkpoint fixture returned no unique metadata receipt")); return; }
      try { resolve(JSON.parse(lines[0].slice("CHECKPOINT_METADATA=".length)) as Fixture); }
      catch { reject(new Error("Checkpoint fixture metadata is not JSON")); }
    });
    child.stdin.end(JSON.stringify({ kind, token: randomUUID(), original_answer: originalAnswer, withdraw: true }));
  });
}

async function sessionRow(fixture: Fixture) {
  const [row] = await queryRaw("SELECT loop_state,loop_state_rev,ended_at,close_json FROM sessions WHERE id=$1", [fixture.session_id]);
  return row as { loop_state: State; loop_state_rev: number; ended_at: string | null; close_json: string | null };
}

async function learningRows(fixture: Fixture) {
  const [counts] = await queryRaw(
    `SELECT (SELECT count(*)::int FROM learning_evidence_operations WHERE operation_id=$1::uuid AND user_id=$2) AS receipts,
       (SELECT count(*)::int FROM node_mastery_events WHERE node_id=$3 AND event_type='evidence') AS evidence,
       (SELECT count(*)::int FROM node_mastery_events WHERE node_id=$3 AND session_id=$4 AND question_hash=$5) AS matching`,
    [fixture.operation_id, USER_LOOP, fixture.node_id, fixture.session_id, fixture.question_hash],
  );
  const states = await queryRaw("SELECT p_known,opps,n_strong_unassisted FROM learner_state WHERE user_id=$1 AND node_id=$2", [USER_LOOP, fixture.node_id]);
  const mirrors = await queryRaw("SELECT mastery_score,times_studied FROM graph_nodes WHERE id=$1", [fixture.node_id]);
  const events = await queryRaw("SELECT id,correct,session_id,question_hash,planning_observation FROM node_mastery_events WHERE node_id=$1 ORDER BY evidence_seq,id", [fixture.node_id]);
  const receipts = await queryRaw("SELECT operation_id,input_fingerprint,plan,changes,committed_at FROM learning_evidence_operations WHERE operation_id=$1::uuid AND user_id=$2", [fixture.operation_id, USER_LOOP]);
  return { counts, states, mirrors, events, receipts };
}

async function signIn(browser: Browser, width: number) {
  const context = await browser.newContext({ storageState: await mintStorageState(USER_LOOP, "Lou Loop"), viewport: { width, height: 844 } });
  await context.addInitScript(LOOP_STREAM_CAPTURE_SCRIPT);
  await context.addInitScript(() => localStorage.setItem("sapling_disclaimer_ack", "true"));
  return { context, page: await context.newPage() };
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
}

for (const kind of ["check", "probe"] as const) {
  for (const width of [1440, 390]) {
    test(`${kind} saved grade survives withdrawal and reload, then commits once at ${width}px`, async ({ browser }, testInfo) => {
      test.skip(killSwitchLane, "loop recovery: default lane only");
      test.setTimeout(120_000);
      const originalAnswer = `Synthetic original saved answer ${randomUUID()}`;
      const fixture = await holdGrade(kind, originalAnswer);
      expect(fixture).toMatchObject({ kind, grader_calls: 1, withdrawn: true });
      expect(fixture.item_id).toMatch(/^e2e-checkpoint-/);
      expect(await queryRaw("SELECT id FROM check_items WHERE id=$1", [fixture.item_id])).toEqual([]);
      const held = await sessionRow(fixture);
      const entry = kind === "check" ? held.loop_state.steps![fixture.question_hash] : held.loop_state.probe!.current!;
      expect(entry.grading_claim).toBe(fixture.operation_id);
      // Discover the module's private key without duplicating its literal in UI.
      const cipherKeys = Object.keys(entry).filter((key) => key.includes("checkpoint"));
      expect(cipherKeys).toHaveLength(1);
      expect(typeof (entry as Record<string, unknown>)[cipherKeys[0]]).toBe("string");
      expect(JSON.stringify(held.loop_state)).not.toContain(originalAnswer);
      const baseline = await learningRows(fixture);
      expect(baseline.counts).toEqual({ receipts: 0, evidence: 0, matching: 0 });
      expect(baseline.states).toEqual([]);
      const usageBefore = await queryRaw("SELECT id FROM llm_usage WHERE user_id=$1 ORDER BY id", [USER_LOOP]);
      const { context, page } = await signIn(browser, width);
      const posts: Array<{ path: string; body: unknown }> = [];
      page.on("request", (request) => {
        const path = new URL(request.url()).pathname;
        if (request.method() === "POST" && path.startsWith("/api/learn/loop/")) posts.push({ path, body: request.postDataJSON() });
      });
      try {
        await page.goto(`/learn?course=rich-course-cs101&resume=${fixture.session_id}`);
        await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-session-id", fixture.session_id);
        await expect(page.getByTestId("loop-pending-grade")).toBeVisible();
        await expect(page.getByTestId("loop-recover-grade")).toBeEnabled();
        if (kind === "check") await expect(page.getByTestId("loop-close-button")).toBeDisabled();
        else await expect(page.getByTestId("loop-close-button")).toHaveCount(0);
        await expectNoOverflow(page);
        await page.reload();
        await expect(page.getByTestId("loop-pending-grade")).toBeVisible();
        expect(posts.filter((post) => /\/(chat|check\/answer|probe\/answer|start-session)/.test(post.path))).toEqual([]);
        const base = { session_id: fixture.session_id, user_id: USER_LOOP };
        const status = await page.request.get(`/api/learn/loop/status?user_id=${USER_LOOP}&session_id=${fixture.session_id}`);
        expect(status.status()).toBe(200);
        const publicStatus = await status.json();
        expect(publicStatus.pending_grade).toEqual({ kind, question_hash: fixture.question_hash });
        expect(JSON.stringify(publicStatus)).not.toContain(fixture.operation_id);
        expect(JSON.stringify(publicStatus)).not.toContain(cipherKeys[0]);
        const blockedChat = await page.request.post("/api/learn/loop/chat", { data: { ...base, message: "continue" } });
        expect(blockedChat.status()).toBe(409);
        const blockedClose = await page.request.post("/api/learn/loop/close", { data: base });
        expect(blockedClose.status()).toBe(409);
        expect(await sessionRow(fixture)).toEqual(held);
        expect(await learningRows(fixture)).toEqual(baseline);
        expect(await queryRaw("SELECT id FROM llm_usage WHERE user_id=$1 ORDER BY id", [USER_LOOP])).toEqual(usageBefore);

        const endpoint = `/api/learn/loop/${kind === "check" ? "check/answer/stream" : "probe/answer"}`;
        const request = page.waitForRequest((request) => new URL(request.url()).pathname === endpoint);
        const response = page.waitForResponse((response) => new URL(response.url()).pathname === endpoint);
        const stream = kind === "check" ? await markLoopStream(page, endpoint) : null;
        await page.getByTestId("loop-recover-grade").click();
        const actualBody = (await request).postDataJSON();
        expect(actualBody).toMatchObject({ ...base, question_hash: fixture.question_hash, idk: false });
        expect(actualBody.answer ?? "").toBe("");
        expect(actualBody.reason ?? "").toBe("");
        expect((await response).status()).toBe(200);
        if (stream) {
          const expectedNotice = ["withdrawn", "recorded"];
          const result = await readLoopStream(page, stream, expectedNotice);
          expect(loopStreamCompleted(result, expectedNotice.length), JSON.stringify(result)).toBe(true);
          expect(result).toMatchObject({ status: 200, phase: "feedback", graded: true, finished: true, eof: true, error_count: 0, done_count: 1, nonempty_reply: true });
        } else {
          expect(await (await response).json()).toMatchObject({ graded: true, correct: false });
        }
        await expect(page.getByTestId("loop-pending-grade")).toHaveCount(0);
        if (kind === "probe") {
          // The withdrawn item has no reference to show; wait for its real next
          // pose (or plan) before reading the resulting session continuation.
          await expect.poll(async () => {
            const phase = await page.getByTestId("loop-phase").getAttribute("data-phase");
            const unknown = page.getByTestId("loop-probe-idk");
            return phase === "plan" || (await unknown.isVisible() && await unknown.isEnabled());
          }).toBe(true);
        }
        await expectNoOverflow(page);
        const final = await sessionRow(fixture);
        expect(final.ended_at).toBeNull();
        expect(final.close_json).toBeNull();
        expect(final.loop_state.goal).toEqual(held.loop_state.goal);
        expect(final.loop_state.goal_version).toEqual(held.loop_state.goal_version);
        const result = await learningRows(fixture);
        expect(result.counts).toEqual({ receipts: 1, evidence: 1, matching: 1 });
        expect(result.receipts).toHaveLength(1);
        expect(result.receipts[0].operation_id).toBe(fixture.operation_id);
        expect(result.receipts[0].input_fingerprint).toMatch(/^[0-9a-f]{64}$/);
        const plan = result.receipts[0].plan as { events: Array<{ id: string }> };
        expect(plan.events).toHaveLength(1);
        expect(plan.events[0].id).toBe(result.events[0].id);
        expect(result.states).toHaveLength(1);
        expect(result.states[0]).toMatchObject({ opps: 1, n_strong_unassisted: 0 });
        expect(result.mirrors[0]).toMatchObject({ times_studied: 1, mastery_score: result.states[0].p_known });
        expect(result.events[0]).toMatchObject({ correct: false, session_id: fixture.session_id, question_hash: fixture.question_hash,
          planning_observation: { idk: true, correct: false, synthetic_idk: false } });
        if (kind === "check") {
          expect(final.loop_state.steps![fixture.question_hash]).toMatchObject({ graded: 1, graded_operation_id: fixture.operation_id, last_correct: false, last_verdict: "idk" });
          expect(final.loop_state.steps![fixture.question_hash]).not.toHaveProperty(cipherKeys[0]);
          const messages = await queryRaw("SELECT content FROM messages WHERE session_id=$1 AND role='user' ORDER BY created_at", [fixture.session_id]);
          expect(messages).toHaveLength(1);
          expect(messages[0].content).not.toBe(originalAnswer);
          expect(await decryptText(messages[0].content as string)).toBe(originalAnswer);
        } else {
          expect(final.loop_state.probe!.history).toHaveLength(1);
          expect(final.loop_state.probe!.history![0]).toMatchObject({ grade_operation_id: fixture.operation_id, idk: true, correct: false });
        }
        const duplicate = await page.request.post(`/api/learn/loop/${kind === "check" ? "check/answer" : "probe/answer"}`, {
          data: { ...base, question_hash: fixture.question_hash, idk: false, answer: "E2E_GRADER_CORRECT" },
        });
        expect(duplicate.status()).toBe(409);
        expect(await learningRows(fixture)).toEqual(result);
        expect(await sessionRow(fixture)).toEqual(final);
        await page.reload();
        await expect(page.getByTestId("loop-phase")).toHaveAttribute("data-session-id", fixture.session_id);
        await expect(page.getByTestId("loop-pending-grade")).toHaveCount(0);
        expect(await learningRows(fixture)).toEqual(result);
        await expectNoOverflow(page);
        await testInfo.attach("grade-recovery-metadata", { contentType: "application/json", body: Buffer.from(JSON.stringify({
          kind, width, checkpoint_created_by_actual_grade: true, interrupted_before_evidence: true,
          withdrawn_synthetic_item: true, original_idk_preserved: true, receipts: 1, evidence: 1, opportunities: 1,
          duplicate_status: duplicate.status(), overflow: false,
        })) });
      } finally { await context.close(); }
    });
  }
}
