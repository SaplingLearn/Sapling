import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from db.connection import like_literal, pg_quote_value, table
from db.scope import service_scope, service_route
from models import OnboardingBody
from services import legal
from services.academics import onboarding_term, resolve_offering, user_enrolled_course_ids
from services.auth_guard import require_self
from services.chunk_visibility import resync_user_chunk_visibility
from services.encryption import encrypt_if_present

logger = logging.getLogger(__name__)

router = APIRouter()


# Words that join a course title but carry no search signal. Dropped only when
# the query has other tokens, because "and" never matches a title written with
# "&" and a stray "of" would otherwise be one more substring that must hit.
_STOPWORDS = frozenset({"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with"})
_MAX_TOKENS = 8
_CANDIDATES = 200
_RESULTS = 20
# A token is a run of letters or a run of digits, so "FE223", "fe-223" and
# "FE 223" all tokenize to ["fe", "223"].
_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.casefold())


def _search_tokens(q: str) -> list[str]:
    """Query tokens the DB filter ANDs together (stopwords dropped, capped)."""
    toks = list(dict.fromkeys(_tokens(q)))  # de-dupe, keep order
    kept = [t for t in toks if t not in _STOPWORDS]
    return (kept or toks)[:_MAX_TOKENS]


def _score(row: dict, q_tokens: list[str], phrase: str) -> int:
    """Rank one candidate: an exact code beats a partial code beats a title."""
    code_toks = _tokens(row.get("course_code") or "")
    name = " ".join(_tokens(row.get("course_name") or ""))
    name_words = name.split()
    score = 0
    # "fe 223" / "FE223" / "qst fe 223" all name QST FE 223: the query is the
    # code, or its tail with the school prefix left off.
    if q_tokens and len(q_tokens) <= len(code_toks) and code_toks[-len(q_tokens):] == q_tokens:
        score += 100
    for t in q_tokens:
        if t in code_toks:
            score += 10
        elif any(c.startswith(t) for c in code_toks):
            score += 5
        if any(w.startswith(t) for w in name_words):
            score += 3
    if phrase:
        if name == phrase:
            score += 40
        elif name.startswith(phrase):
            score += 20
        elif phrase in name:
            score += 10
    return score


# #115: public (no session) catalog search -> service role under db_user_scope.
@router.get("/courses", dependencies=[Depends(service_route)])
def search_courses(request: Request, q: str = Query("", min_length=0)):
    """Search courses by code and/or name. Returns the first page if q is empty.

    Students type codes every which way — "QST FE 223", "FE 223", "fe223",
    "FE-223" — and names loosely ("intro to corporate finance", "corporate
    finance", "FE 223 corporate finance"). One substring over the whole query
    matched only the first two code forms and only verbatim titles, so the
    query is split into letter/digit tokens and EVERY token must appear in the
    code or the name (any order). The candidates are then ranked in Python so
    the course whose code the student typed comes first, ahead of the courses
    that merely contain those characters.

    The catalog can hold DISTINCT abstract courses (different ids, sometimes
    different names) that share a course_code — e.g. the seed-* and rich-* demo
    schools each define their own "CS101"/"BIO110". Without disambiguation the
    picker showed them as indistinguishable duplicates (finding F2). Collapse by
    normalized course_code, keeping the best-ranked row per code, so each code
    appears exactly once. Rows with a blank code are never collapsed together.
    """
    filters = {}
    q_tokens: list[str] = []
    if q.strip():
        q_tokens = _search_tokens(q)
        if not q_tokens:
            # Nothing searchable (only punctuation) — not the same as blank.
            return {"courses": []}
        # Tokens are letters or digits only, so nothing in them can split the
        # PostgREST logic tree or act as a LIKE wildcard; the quoting stays as
        # the grammar's own rule for any value interpolated into a tree.
        clauses = []
        for t in q_tokens:
            needle = pg_quote_value(f"%{like_literal(t)}%")
            clauses.append(f"or(course_name.ilike.{needle},course_code.ilike.{needle})")
        filters["and"] = f"({','.join(clauses)})"

    rows = table("courses").select(
        "id,course_code,course_name",
        filters=filters,
        order="course_name.asc",
        limit=_CANDIDATES if q_tokens else _RESULTS,
    )

    if q_tokens:
        phrase = " ".join(_tokens(q))
        # sorted() is stable, so equal scores keep the DB's name order.
        rows = sorted(rows, key=lambda r: -_score(r, q_tokens, phrase))

    deduped = []
    seen_codes = set()
    for row in rows:
        code = (row.get("course_code") or "").strip().casefold()
        if code:
            if code in seen_codes:
                continue
            seen_codes.add(code)
        deduped.append(row)
        if len(deduped) == _RESULTS:
            break

    return {"courses": deduped}


#: The `detail.code` of this route's 422s; the frontend maps each to its copy.
LEGAL_OUTDATED = "legal_outdated"
NO_KNOWN_COURSES = "no_known_courses"

# Postgres unique_violation. PostgREST answers it with a 409, as it does a
# foreign-key violation, so only the body's SQLSTATE tells the two apart.
_UNIQUE_VIOLATION = "23505"


def _is_unique_violation(exc: httpx.HTTPStatusError) -> bool:
    if exc.response is None or exc.response.status_code != 409:
        return False
    try:
        body = exc.response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") == _UNIQUE_VIOLATION


def _known_course_ids(course_ids: list[str]) -> list[str]:
    """The requested course ids the catalog has, in the order the student
    picked them. One read; each id is quoted, since it is the client's."""
    if not course_ids:
        return []
    rows = table("courses").select(
        "id",
        filters={"id": f"in.({','.join(pg_quote_value(c) for c in course_ids)})"},
    ) or []
    found = {r.get("id") for r in rows}
    return [c for c in course_ids if c in found]


def _enroll(user_id: str, offering_id: str) -> None:
    """Insert one enrollment. `enrollments` is UNIQUE (user_id, offering_id)
    (the baseline's user_courses constraint, which followed the 0020 rename),
    so a concurrent or retried submit that loses the race gets a 23505: that
    student is enrolled already, which is the outcome this wanted."""
    try:
        table("enrollments").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "offering_id": offering_id,
        })
    except httpx.HTTPStatusError as exc:
        if not _is_unique_violation(exc):
            raise


def _enroll_in_courses(user_id: str, course_ids: list[str], term_id: str) -> int:
    """Enroll the student in each course's offering of `term_id` and return
    how many of the courses they now hold.

    A course already held in ANY term counts as linked and is not enrolled
    again: the no-retake rule `graph_service.add_course` applies, and it keeps
    a retry that lands after a term boundary from stacking a second
    enrollment in the next term."""
    held = user_enrolled_course_ids(user_id)
    linked = 0
    for course_id in course_ids:
        if course_id not in held:
            # Creates a sectionless offering when the catalog lacks one for
            # the term ("sectionless" is '' since 0033, not NULL).
            offering_id = resolve_offering(course_id, term_id, create=True)
            if not offering_id:
                # resolve_offering with a term id finds, creates or raises.
                raise RuntimeError(f"no offering of {course_id} in term {term_id}")
            _enroll(user_id, offering_id)
        linked += 1
    return linked


@router.post("/profile")
def save_onboarding_profile(
    body: OnboardingBody, request: Request, background_tasks: BackgroundTasks,
):
    """Save the onboarding form for an existing user — once.

    #757: onboarding is a one-way gate. A replay by an already-onboarded user
    is a 409 (it used to overwrite the profile and add enrollments).

    The order is the contract's, and everything the account needs is written
    BEFORE `onboarding_completed`, so a failure part-way leaves the account
    un-onboarded and retryable instead of "onboarded" with no profile, no
    courses, a minor's sharing still on, or no record of the accepted terms:

    1. validate. The accepted Terms / Privacy versions must be the current ones
       (422 `legal_outdated`) and, when courses were picked, at least one must
       be in the catalog (422 `no_known_courses`). Reads only: a refused
       submit writes nothing. An empty `course_ids` is allowed ("my courses
       aren't listed, I'll add them later").
    2. the profile: names (encrypted) and year;
    3. enrollments, in the onboarding term (`academics.onboarding_term`);
    4. an under-18 student's privacy: profile private, Class Intel sharing
       off, in `user_settings` (the store the settings PATCH writes);
    5. the two legal acceptances (`legal_acceptances`, append-only);
    6. `onboarding_completed`, only from false.

    Every write before the flag is idempotent (profile upsert, enrollments
    that treat "already enrolled" as done, settings upsert, acceptances
    inserted once), which is what makes that retry safe.
    """
    require_self(body.user_id, request)
    user_id = body.user_id

    user = table("users").select(
        "id,onboarding_completed", filters={"id": f"eq.{user_id}"},
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user[0].get("onboarding_completed"):
        raise HTTPException(status_code=409, detail="Onboarding is already complete.")

    # 1. Validate (reads only).
    if not legal.accepted_current(body.accepted_terms_version, body.accepted_privacy_version):
        raise HTTPException(status_code=422, detail={
            "code": LEGAL_OUTDATED,
            "message": (
                "Our Terms of Service or Privacy Policy changed while you were "
                "signing up. Please review and accept the current versions."
            ),
        })
    course_ids = _known_course_ids(body.course_ids)
    if body.course_ids and not course_ids:
        raise HTTPException(status_code=422, detail={
            "code": NO_KNOWN_COURSES,
            "message": (
                "We couldn't find any of the courses you picked. Search for them "
                "again, or skip this step and add your courses later."
            ),
        })
    term = onboarding_term() if course_ids else None
    if course_ids and term is None:
        # No term is seeded at all, so there is nothing to enroll into: the
        # server's problem, not the student's, and nothing is written.
        logger.error("onboarding: no term to enroll %s into", user_id)
        raise HTTPException(
            status_code=503,
            detail="Adding courses isn't available right now. Please try again in a moment.",
        )

    # 2. Profile fields moved to user_profiles in migration 0024 (one source
    # of truth). name/first_name/last_name are 🔒-encrypted; the rest plaintext.
    name = f"{body.first_name} {body.last_name}".strip()
    table("user_profiles").upsert(
        {
            "user_id": user_id,
            "name": encrypt_if_present(name),
            "first_name": encrypt_if_present(body.first_name),
            "last_name": encrypt_if_present(body.last_name),
            "year": body.year,
            "majors": body.majors,
            "minors": body.minors,
            "learning_style": body.learning_style,
        },
        on_conflict="user_id",
    )

    # 3. Enrollments. The response reports how many courses are linked.
    courses_linked = _enroll_in_courses(user_id, course_ids, term["id"]) if course_ids else 0

    # 4. A minor starts private, server-side: the birthday screen promises it,
    # and a client-side PATCH after completion could fail or never be sent.
    if body.under_18:
        table("user_settings").upsert(
            {
                "user_id": user_id,
                "profile_visibility": "private",
                "share_class_context": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id",
        )
        # As the settings PATCH does when sharing goes off (#629): withdraw
        # anything this account already put in a shared course pool.
        # Idempotent, and a no-op for an account with no uploads.
        background_tasks.add_task(resync_user_chunk_visibility, user_id)

    # 5. What the student accepted, before the account counts as onboarded.
    legal.record_acceptances(
        user_id,
        terms_version=body.accepted_terms_version,
        privacy_version=body.accepted_privacy_version,
    )

    # 6. onboarding_completed is an auth/status flag and stays on `users`.
    # Last, and only from false: a concurrent submit that got here first wins.
    # #115: `users` is account state (SELECT-only for the student's token).
    with service_scope():
        table("users").update(
            {"onboarding_completed": True},
            filters={"id": f"eq.{user_id}", "onboarding_completed": "is.false"},
        )

    return {
        "ok": True,
        "user_id": user_id,
        "courses_linked": courses_linked,
    }
