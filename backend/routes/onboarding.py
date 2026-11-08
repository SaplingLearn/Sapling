import re
import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import like_literal, pg_quote_value, table
from models import OnboardingBody
from services.academics import resolve_offering
from services.auth_guard import require_self
from services.encryption import encrypt_if_present

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


@router.get("/courses")
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


@router.post("/profile")
def save_onboarding_profile(body: OnboardingBody, request: Request):
    """Save the onboarding form data for an existing user — once.

    #757: onboarding is a one-way gate. A replay by an already-onboarded user
    is a 409 (it used to overwrite the profile and add enrollments), and
    `onboarding_completed` is written LAST, so a failure part-way leaves the
    account un-onboarded and retryable instead of "onboarded" with no profile.
    Every write before the flag is idempotent (profile upsert, enrollment
    existence check), which is what makes that retry safe.
    """
    require_self(body.user_id, request)

    user = table("users").select(
        "id,onboarding_completed", filters={"id": f"eq.{body.user_id}"},
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user[0].get("onboarding_completed"):
        raise HTTPException(status_code=409, detail="Onboarding is already complete.")

    # Profile fields moved to user_profiles in migration 0024 (one source of truth).
    # name/first_name/last_name are 🔒-encrypted; the rest are plaintext.
    name = f"{body.first_name} {body.last_name}".strip()
    table("user_profiles").upsert(
        {
            "user_id": body.user_id,
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

    # Enroll user in selected courses (resolve each abstract course → current-term offering)
    enrolled_ids = []
    for course_id in body.course_ids:
        # Verify abstract course exists in the catalog
        course = table("courses").select("id", filters={"id": f"eq.{course_id}"})
        if not course:
            continue

        # Resolve the abstract course to a current-term offering, creating a
        # sectionless one if the catalog lacks one for this term. "Sectionless"
        # is the empty string, not NULL, since 0033 made section NOT NULL
        # DEFAULT ''.
        offering_id = resolve_offering(course_id, create=True)
        if not offering_id:
            continue

        # Enroll if not already enrolled in this offering
        existing = table("enrollments").select(
            "id",
            filters={
                "user_id": f"eq.{body.user_id}",
                "offering_id": f"eq.{offering_id}",
            },
        )
        if not existing:
            table("enrollments").insert({
                "id": str(uuid.uuid4()),
                "user_id": body.user_id,
                "offering_id": offering_id,
            })

        enrolled_ids.append(course_id)  # response still reports abstract course ids

    # onboarding_completed is an auth/status flag and stays on `users`. Last,
    # and only from false: a concurrent submit that got here first wins.
    table("users").update(
        {"onboarding_completed": True},
        filters={"id": f"eq.{body.user_id}", "onboarding_completed": "is.false"},
    )

    return {
        "user_id": body.user_id,
        "courses_linked": enrolled_ids,
    }
