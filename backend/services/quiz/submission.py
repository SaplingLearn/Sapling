"""
backend/services/quiz/submission.py — moved from routes/quiz.py (#118).

POST /submit: grading a claimed attempt, the score/mastery writes, the
background quiz-context update and the G8 gamification block.

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import json
import logging
import os
from datetime import datetime, timezone

from starlette.background import BackgroundTasks
from starlette.requests import Request

import config
from agents._providers import UnregisteredHandlerError
from agents._run import run_agent_sync
from agents.quiz_context import quiz_context_agent
from agents.usage import record_agent_usage
from db.connection import table
from models import SubmitQuizBody
from services import events_service
from services import llm_budget
from services.quiz.config import mastery_after
from services.quiz.errors import QuizAPIError, QuizErrorCode
from services.profiles import get_display_name
from services.encryption import encrypt_json, decrypt_json_column
from services.quiz.grading import WRITTEN_TYPES, grade_written
from services.graph_service import apply_graph_update
from services.quiz.context import get_quiz_context, save_quiz_context
from services.quiz.distractors import build_distractor_profile
from services.gamification_service import me_snapshot
from services.xp_service import XpAward, award_xp_safe
from services.request_context import current_request_id
from services.quiz.attempts import (
    _already_completed,
    _attempt_not_found,
    _load_owned_attempt,
    _refuse_if_abandoned,
    _refuse_if_completed,
)
from services.quiz.wire import _written_response_text

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


# One dirname more than in routes/quiz.py: this file sits a level deeper.
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts")


def _load_prompt(name: str) -> str:
    with open(os.path.join(PROMPTS_DIR, name)) as f:
        return f.read()


def _gamification_block(
    user_id: str, award: XpAward | None, quiz_id: str,
) -> dict:
    """G8: the XP/streak numbers the results screen needs, in the submit reply.

    Before this the close screen had to read `GET /api/gamification/me` once
    before the session and once after the submit and subtract — two extra
    round trips whose race or failure showed the student a blank where their
    XP should be (`frontend/src/lib/quiz/useGamificationDelta.ts`). The
    snapshot is built by `services/gamification_service.me_snapshot`, the same
    function `/api/gamification/me` serves, so the inline numbers and the
    endpoint can never disagree.

    The block has two independent halves, and each failure is reported as
    itself rather than papered over with a plausible number:

    * the AWARD half (`xp_awarded`, `leveled_up`, `duplicate`) comes off the
      `XpAward` already in memory and costs no query. All three are `None`
      TOGETHER when the XP write failed and `award_xp_safe` swallowed it —
      there is no award to report, and the client's rule is to omit the XP
      line rather than invent one.
    * the CARD half is the `/me` snapshot. If that read fails the award half
      still ships ALONE. It cost nothing to produce, the `/me` fallback that
      would otherwise supply it is aimed at the same database that just
      failed, and R-9a tells a migrated client to have dropped those reads
      entirely — so the fallback is least likely to work on exactly the
      request that needs it.

    `leveled_up` and `duplicate` ride along because a client cannot
    reconstruct either: three different paths all report `xp_awarded: 0` (a
    disabled rule, a zero-amount rule, an idempotent replay), and spotting a
    level-up without `leveled_up` means re-adding the round trip this block
    exists to remove.

    `xp_awarded` is what the `quiz_completed` award paid, which is the amount
    written to the `xp_events` ledger. A badge earned by the same submit pays
    its own XP separately; that is not in `xp_awarded` but IS in `total_xp`,
    which is read after the achievement pass.
    """
    paid = {
        "xp_awarded": award.awarded if award else None,
        "leveled_up": award.leveled_up if award else None,
        "duplicate": award.duplicate if award else None,
    }
    try:
        snapshot = me_snapshot(user_id)
    except Exception:
        # Display data must never fail the action that earned it — the same
        # rule `award_xp_safe` follows for the write itself. But swallowing it
        # silently is what let #529 live 51 days undetected in this very
        # function, so the log line is paired with a countable event exactly
        # as `_update_context` pairs its own.
        logger.exception(
            "quiz: gamification snapshot failed quiz_id=%s user=%s",
            quiz_id, user_id,
        )
        events_service.log_event(
            "quiz.gamification_snapshot_failed",
            category="error",
            user_id=user_id,
            request_id=current_request_id(),
            payload={"quiz_id": quiz_id},
        )
        return paid
    return {**paid, **snapshot}


def _grade_submission(
    body: SubmitQuizBody, questions: list[dict],
) -> tuple[list[dict], list[dict], int]:
    """Grade a claimed attempt: (results, graded_answers, score)."""
    # #541 C4: responses recorded through /attempts/{id}/answer are the
    # source of truth — a payload answer for the same question is ignored
    # (the recorded response was graded at answer time; letting the final
    # POST override it would reopen the client-side-grading hole C exists
    # to close). Questions never answered through C1 fall back to the
    # submitted payload, so the current all-at-the-end client keeps working.
    recorded_rows = table("quiz_responses").select(
        "question_index,selected_index,answer_text",
        filters={"attempt_id": f"eq.{body.quiz_id}"},
    ) or []
    recorded_by_index = {r["question_index"]: r for r in recorded_rows}

    answer_map = {str(a.question_id): a.selected_label for a in body.answers}
    results = []
    # The reconciled answer set — what was ACTUALLY graded, which is what
    # answers_json must persist. Storing the raw payload instead left a
    # recorded-only submit with a full score beside an empty answer list,
    # and a contradicted payload answer stored despite losing to the
    # recorded response.
    graded_answers: list[dict] = []
    score = 0
    for q_index, q in enumerate(questions):
        qid = str(q["id"])
        recorded = recorded_by_index.get(q_index)
        if q.get("type") in WRITTEN_TYPES:
            # Written responses must have been accepted through /answer. Never
            # let a submission payload override the first recorded response.
            selected_text = _written_response_text(recorded) if recorded else ""
            is_correct = grade_written(q, selected_text)
            if selected_text:
                graded_answers.append({"question_id": q["id"], "answer_text": selected_text})
            score += int(is_correct)
            results.append({"question_id": qid, "selected": selected_text,
                            "correct": is_correct, "correct_answer": q.get("correct_answer", ""),
                            "explanation": q.get("explanation", "")})
            continue
        if recorded is not None:
            sel_idx = recorded.get("selected_index")
            options = q.get("options", [])
            selected = (
                options[sel_idx]["label"]
                if isinstance(sel_idx, int) and 0 <= sel_idx < len(options)
                else ""
            )
        else:
            selected = answer_map.get(qid, "")
        if selected:
            graded_answers.append({
                "question_id": q["id"],
                "selected_label": selected,
            })
        correct_opt = next((o for o in q["options"] if o.get("correct")), None)
        correct_label = correct_opt["label"] if correct_opt else ""
        # #129: a malformed item with NO correct option must never grade as
        # correct — '' == '' would otherwise hand a free point whenever the
        # answer is also missing.
        is_correct = bool(correct_opt) and selected == correct_label
        if is_correct:
            score += 1
        results.append({
            "question_id": qid,
            "selected": selected,
            "correct": is_correct,
            "correct_answer": correct_label,
            "explanation": q.get("explanation", ""),
        })

    return results, graded_answers, score


def _release_submit_claim(quiz_id: str, claim_stamp: str) -> None:
    """Undo the submit claim when grading/scoring failed before any write.

    Conditional on THIS request's stamp and a still-NULL score, so it can
    only reopen the row this request closed and never one that was scored.
    Best-effort: if the release itself fails the attempt stays stranded,
    which is logged loudly rather than masking the original error.
    """
    try:
        table("quiz_attempts").update(
            {"completed_at": None},
            filters={
                "id": f"eq.{quiz_id}",
                "completed_at": f"eq.{claim_stamp}",
                "score": "is.null",
            },
            prefer_return_minimal=True,
        )
    except Exception:
        logger.exception(
            "quiz: submit claim release failed; attempt stranded "
            "completed-but-scoreless quiz_id=%s", quiz_id,
        )


def submit_quiz(body: SubmitQuizBody, background_tasks: BackgroundTasks, request: Request):
    attempt = _load_owned_attempt(body.quiz_id, request)
    user_id = attempt["user_id"]

    # #521: ciphertext str for new rows, plaintext JSONB for pre-backfill rows.
    questions = decrypt_json_column(attempt["questions_json"])

    # #129: completed_at is written on the first successful submit. A re-POST
    # of the same quiz_id must not re-run apply_graph_update (double mastery
    # delta + duplicate node_mastery_events row + streak bump), the background
    # quiz-context task, or achievements. 409 rather than replaying the original
    # 200: quiz_attempts stores no mastery_before/after, so faithfully
    # reconstructing the first response would need a migration.
    _refuse_if_completed(attempt)
    # An abandoned attempt must not pay out mastery, XP or achievements —
    # otherwise the TTL is a label and the sweep enforces nothing.
    _refuse_if_abandoned(attempt)

    concept_node_id = attempt["concept_node_id"]

    # Owner-scoped read: the attempt's concept node must belong to the
    # attempt's owner. A missing/foreign node means we'd otherwise write
    # mastery to someone else's row (IDOR) — refuse before any write.
    # mastery_events was DROPPED in 0023 (events moved to node_mastery_events);
    # we no longer read or write that column here.
    #
    # #760: BEFORE the claim. A pure precondition that 404s after the claim
    # stranded the attempt completed-but-scoreless — every retry 409'd and no
    # XP was ever paid. Refusing here leaves the attempt open.
    node_rows = table("graph_nodes").select(
        "concept_name,mastery_score,course_id",
        filters={"id": f"eq.{concept_node_id}", "user_id": f"eq.{user_id}"},
    )
    if not node_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_CONCEPT_NOT_FOUND,
            message="We couldn't find that concept in your knowledge graph.",
        )
    node = node_rows[0]

    # The read above is only the fast path — two CONCURRENT submits (a
    # double-click on the final submit) would both pass it. The atomic claim
    # below (conditional update on completed_at IS NULL, PR #464 review) is
    # the real gate: exactly one request wins the row; the loser 409s before
    # any mastery write.
    #
    # #760: once claimed, the SCORE must land. Grading + the score write come
    # next, and a failure in them releases the claim (nothing else has been
    # written yet, so a retry is safe). The graph/mastery update runs only
    # after the score is persisted and is best-effort: its failure is logged
    # and emitted, never allowed to strand the attempt scoreless.
    claim_stamp = datetime.now(timezone.utc).isoformat()
    claimed = table("quiz_attempts").update(
        {"completed_at": claim_stamp},
        filters={
            "id": f"eq.{body.quiz_id}",
            "completed_at": "is.null",
            # Symmetric with abandon_attempt's claim (#537 G4). Without it the
            # two claims can BOTH win — mid-quiz in one tab, Discard in
            # another — and the row ends up completed AND abandoned.
            # `_refuse_if_abandoned` above is only a pre-read; the filters are
            # what actually arbitrate.
            "abandoned_at": "is.null",
        },
    )
    if not claimed:
        # Two ways to lose the claim now, and they are different sentences to
        # the student ("already submitted" vs "you discarded this"). The
        # pre-read cannot see a stamp written since, so re-read rather than
        # assume the completed case.
        #
        # That re-read is a REFINEMENT of an answer this branch already has.
        # Losing the claim used to be infallible — no I/O between the refusal
        # and the response — so a transient PostgREST failure here must fall
        # back to the 409 a double-submit always got, not turn an ordinary
        # double-click into a 500.
        try:
            current_rows = table("quiz_attempts").select(
                "abandoned_at", filters={"id": f"eq.{body.quiz_id}"},
            )
        except Exception:
            logger.warning(
                "quiz: submit re-read failed after a lost claim attempt=%s; "
                "answering already-completed", body.quiz_id, exc_info=True,
            )
            current_rows = None
        if current_rows is not None:
            if not current_rows:
                # Deleted under us: neither sentence is true any more.
                raise _attempt_not_found()
            _refuse_if_abandoned(current_rows[0])
        raise _already_completed()

    try:
        results, graded_answers, score = _grade_submission(body, questions)
        total = len(questions)
        # The score lands FIRST and alone (#760): everything after it is
        # best-effort, so nothing after it can strand the attempt scoreless.
        table("quiz_attempts").update(
            {
                "score": score,
                "total": total,
                # The reconciled set (recorded responses winning over payload),
                # not the raw request — the attempt's stored answers must agree
                # with the score computed from them.
                "answers_json": encrypt_json(graded_answers),
                # completed_at was already stamped by the atomic claim above.
            },
            filters={"id": f"eq.{body.quiz_id}"},
        )
    except Exception:
        # Nothing else has been written: hand the attempt back so a retry
        # can grade it, rather than leave it completed with no score.
        _release_submit_claim(body.quiz_id, claim_stamp)
        raise

    mastery_before = node["mastery_score"]
    # #543 E1: the model is a named seam now (services/quiz_config.py).
    # The numbers are unchanged — see docs/quiz-mastery-model.md for the
    # options the revamp gets to choose from.
    mastery_score_after = mastery_after(mastery_before, score=score, total=total)
    mastery_delta = mastery_score_after - mastery_before

    # E7: the categorical reading of the attempt, namespaced by producer.
    # `node_mastery_events.event_type` has two independent writers and no
    # CHECK constraint — this route and the tutor's `update_mastery_tool`
    # (tutor_interaction / tutor_correction / tutor_quiz) — so an unprefixed
    # "quiz" or "correct" would leave the column carrying two disjoint
    # vocabularies with no way to tell which producer wrote a given row.
    score_ratio = score / total if total > 0 else 0.0
    if score_ratio >= 0.7:
        event_type = "quiz_correct"
    elif score_ratio >= 0.4:
        event_type = "quiz_partial"
    else:
        event_type = "quiz_confusion"

    # Route the mastery write through the sanctioned graph path. The graph
    # keys on the ABSTRACT course id; apply_graph_update looks the node up by
    # (normalized) concept_name within (user_id, course_id), clamps mastery,
    # bumps times_studied/last_studied_at, records the event (now in
    # node_mastery_events), and updates the streak. We don't touch graph_nodes
    # or node_mastery_events directly — that's the graph slice's territory.
    #
    # #760: best-effort. The score is already persisted; a graph failure here
    # must not turn a scored submit into a 500 (whose retry would 409 and pay
    # no XP). It is logged and emitted, and the attempt keeps NULL mastery
    # columns — history then shows no delta rather than one the graph never
    # took.
    try:
        applied = apply_graph_update(
            user_id,
            {
                "updated_nodes": [
                    {
                        "concept_name": node["concept_name"],
                        "mastery_delta": mastery_delta,
                        "reason": f"Quiz: {score}/{total} correct",
                        "event_type": event_type,
                    }
                ]
            },
            course_id=node.get("course_id"), defer=background_tasks.add_task,
        )
    except Exception:
        logger.exception(
            "quiz: mastery update failed after scoring quiz_id=%s concept=%s",
            body.quiz_id, concept_node_id,
        )
        events_service.log_event(
            "quiz.mastery_write_failed",
            category="error",
            user_id=user_id,
            request_id=current_request_id(),
            payload={"quiz_id": body.quiz_id, "concept_node_id": concept_node_id},
        )
        mastery_written = False
        # Mastery did not move: report it as unchanged, not as predicted.
        mastery_score_after = mastery_before
        mastery_delta = 0.0
    else:
        mastery_written = True
        # #542 D1 (review): persist what the GRAPH actually wrote, not what
        # we predicted. apply_graph_update owns the write — it resolves the
        # node by normalized concept name and clamps the result — so its
        # reported before/after is the only value that can't disagree with
        # graph_nodes. Falls back to the local computation if the call
        # returned nothing recognisable (it degrades rather than raising).
        for change in applied or []:
            if isinstance(change, dict) and change.get("after") is not None:
                mastery_before = change.get("before", mastery_before)
                # NB: mastery_after is the imported model function (#543 E1);
                # the value lives in mastery_score_after.
                mastery_score_after = change["after"]
                mastery_delta = mastery_score_after - mastery_before
                break

    if mastery_written:
        try:
            table("quiz_attempts").update(
                {
                    # #542 D1: the mastery snapshot — without it a
                    # replayed/audited submit can't reconstruct what the
                    # student saw, and history can't show progression.
                    # Plaintext scalars (#521 rationale).
                    "mastery_before": mastery_before,
                    "mastery_after": mastery_score_after,
                },
                filters={"id": f"eq.{body.quiz_id}"},
            )
        except Exception:
            # The score and the graph both landed; only the history snapshot
            # is missing. Not worth failing the submit that earned it.
            logger.exception(
                "quiz: mastery snapshot write failed quiz_id=%s", body.quiz_id,
            )

    node2_rows = table("graph_nodes").select(
        "concept_name",
        filters={"id": f"eq.{concept_node_id}", "user_id": f"eq.{user_id}"},
    )
    concept_name = node2_rows[0]["concept_name"] if node2_rows else "Unknown"
    # Display name lives on user_profiles (0024); resolve + decrypt via helper.
    student_name = get_display_name(user_id) or "Student"

    existing_ctx = get_quiz_context(user_id, concept_node_id)
    ctx_prompt = (
        _load_prompt("quiz_context_update.txt")
        .replace("{concept_name}", concept_name)
        .replace("{student_name}", student_name)
        .replace("{existing_quiz_context_json}", json.dumps(existing_ctx) if existing_ctx else "{}")
        .replace("{score}", str(score))
        .replace("{total}", str(total))
        .replace("{quiz_results_json}", json.dumps(results, indent=2))
        # H2/#554: the wrong answers in WORDS. `results` carries labels only
        # ("picked B, answer was C"), which is not something a model can turn
        # into a misconception — it can only guess one. The option text lives
        # in questions_json, one join away, and has been sitting unread since
        # answers_json existed.
        .replace(
            "{distractor_profile_json}",
            json.dumps(build_distractor_profile(questions, results), indent=2),
        )
    )

    # Correlate the background write with this request's trace.
    ctx_request_id = getattr(request.state, "request_id", None) or current_request_id()

    def _update_context(prompt: str, uid: str, node_id: str, quiz_id: str,
                        request_id: str | None):
        # #529/B3: this write was `except Exception: pass` for months while
        # every attempt 42P10'd — the adaptive loop died silently. Failures
        # are loud now: ERROR log with the attempt id + request id, a
        # `quiz.context_write_failed` analytics event, and a re-raise in
        # local/test envs so a regression fails CI instead of going quiet.
        try:
            # #119: post-response work — the per-user LLM budget never refuses
            # it (services/llm_budget.py); its tokens still count.
            with llm_budget.background_work():
                run = run_agent_sync(quiz_context_agent.run(prompt))
            result = record_agent_usage(
                run, feature="quiz", task="quiz_context", user_id=uid,
            )
            save_quiz_context(uid, node_id, result.output.model_dump())
        except UnregisteredHandlerError:
            # E2E function mode leaves quiz_context deliberately
            # unregistered (agents/function_handlers_e2e.py) so no
            # post-response DB write races the next test's re-seed. One
            # WARNING, no traceback: the logscan oracle reports tracebacks.
            logger.warning(
                "quiz: context update skipped — quiz_context handler "
                "unregistered (function-mode seam) quiz_id=%s", quiz_id,
            )
        except Exception:
            logger.exception(
                "quiz: context update failed quiz_id=%s concept=%s "
                "request_id=%s", quiz_id, node_id, request_id,
            )
            events_service.log_event(
                "quiz.context_write_failed",
                category="error",
                user_id=uid,
                request_id=request_id,
                payload={"quiz_id": quiz_id, "concept_node_id": node_id},
            )
            if config.IS_LOCAL:
                raise

    background_tasks.add_task(
        _update_context, ctx_prompt, user_id, concept_node_id,
        body.quiz_id, ctx_request_id,
    )

    # XP + achievements: after the attempt row (score/total/answers_json) is
    # persisted above (the atomic completed_at claim + the update at :486-494
    # together gate this to exactly one successful submit per attempt id;
    # a replay 409s before reaching here). source_id=body.quiz_id is the
    # attempt id, so a hypothetical double-invocation is a no-op via the
    # xp_events idempotency key rather than a double payout.
    award = award_xp_safe(user_id, "quiz_completed", source_type="quiz",
                          source_id=body.quiz_id)

    # Check for achievements after quiz completion
    try:
        from services.achievement_service import check_achievements
        check_achievements(user_id, "quizzes_completed", {})
    except Exception:
        logger.warning("quizzes_completed achievement check failed", exc_info=True)

    # G8: read AFTER the achievement pass — a badge earned by this submit pays
    # its own XP and moves earned_count, so a snapshot taken before it would
    # be stale the moment it was serialized.
    gamification = _gamification_block(user_id, award, body.quiz_id)

    # #117: quiz.completed on the success path only — a 409 replay (the
    # atomic completed_at claim above) or any earlier 4xx never reaches here.
    events_service.log_event(
        "quiz.completed",
        category="usage",
        user_id=user_id,
        payload={
            "quiz_id": body.quiz_id,
            "concept_node_id": concept_node_id,
            "score": score,
            "total": total,
            "mastery_delta": mastery_delta,
        },
    )

    return {
        "score": score,
        "total": total,
        "mastery_before": mastery_before,
        "mastery_after": mastery_score_after,
        "results": results,
        # G8, additive: what the award paid (`xp_awarded`, `leveled_up`,
        # `duplicate`) plus the /api/gamification/me snapshot as of right now.
        # Always present. If the snapshot read failed it carries the award
        # half ALONE — see `_gamification_block` for why that half survives.
        "gamification": gamification,
    }
