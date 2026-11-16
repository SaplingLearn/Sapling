import re
from typing import Annotated, Optional, Union, List, Literal
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from services.quiz.config import QUIZ_MIN_QUESTIONS, QUIZ_MAX_QUESTIONS


# ── Request-body bounds ───────────────────────────────────────────────────────
#
# Every free-text field a client sends is bounded, so one request cannot carry
# megabytes into an encrypted column, a prompt or a room transcript (a 422
# before the handler runs). The limits are generous for real use; where the
# frontend caps an input (`maxLength`), it uses the same number.

#: Any identifier (user, session, course, room, message, document...). Real ids
#: are UUIDs or `user_<google id>`; 256 is far past both.
ID_MAX = 256
#: One tutor chat / note chat message.
CHAT_MESSAGE_MAX = 8000
#: A tutor session's topic as sent on start (a concept or course name).
TOPIC_MAX = 500
#: One study-room message.
ROOM_MESSAGE_MAX = 4000
#: A profile bio.
BIO_MAX = 500
#: Short labels: names, titles, locations, feedback topics.
SHORT_TEXT_MAX = 200
#: Feedback comments and issue-report descriptions.
LONG_TEXT_MAX = 10_000
#: A URL a client sends (screenshots, assets).
URL_MAX = 2048

Id = Annotated[str, Field(max_length=ID_MAX)]
ShortText = Annotated[str, Field(max_length=SHORT_TEXT_MAX)]
LongText = Annotated[str, Field(max_length=LONG_TEXT_MAX)]
Url = Annotated[str, Field(max_length=URL_MAX)]

#: sessions.mode is CHECK-constrained to these (and agents/chat_tutor.py
#: serves exactly these three).
TutorMode = Literal["socratic", "expository", "teachback"]


# ── Learn ─────────────────────────────────────────────────────────────────────

class StartSessionBody(BaseModel):
    user_id: Id = "user_andres"
    topic: str = Field(default="", max_length=TOPIC_MAX)
    mode: TutorMode = "socratic"
    use_shared_context: bool = True
    course_id: Optional[Id] = None  # Direct course_id lookup instead of resolving from topic
    model_pref: Optional[Literal["fast", "smart"]] = None  # "fast" (default, gemini-2.5-flash) or "smart" (gemini-2.5-pro)
    # Send to tutor's note, when the topic is still that note's title: a crisis
    # match then shows the card beside the session (docs/safety/crisis-support.md).
    # Checked against the student's own note; never trusted on its own.
    from_note_id: Optional[Id] = None


class ChatBody(BaseModel):
    session_id: Id
    user_id: Id = "user_andres"
    message: str = Field(max_length=CHAT_MESSAGE_MAX)
    mode: TutorMode = "socratic"
    use_shared_context: bool = True
    model_pref: Optional[Literal["fast", "smart"]] = None  # "fast" (default, gemini-2.5-flash) or "smart" (gemini-2.5-pro)
    # #761: client-minted id for ONE student turn, sent unchanged on the
    # stream AND on its JSON fallback/retry. Makes the turn's message writes
    # idempotent and lets a re-send of an already-persisted turn replay the
    # stored reply instead of running the turn twice. Optional: without it a
    # turn is not deduplicated across requests.
    turn_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{8,128}$")


class EndSessionBody(BaseModel):
    session_id: Id
    user_id: Id = ""  # Required to discard a lazy (not-yet-persisted) session safely


class RenameSessionBody(BaseModel):
    user_id: Id
    # The route answers 1-120 characters (the frontend's maxLength) with its
    # own 400; this only bounds what is parsed at all.
    topic: str = Field(max_length=TOPIC_MAX)


class ActionBody(BaseModel):
    session_id: Id
    user_id: Id = "user_andres"
    # The prompts services/tutor/turns.py::_action_turn knows.
    action_type: Literal["hint", "confused", "skip"] = "hint"
    mode: TutorMode = "socratic"
    use_shared_context: bool = True
    model_pref: Optional[Literal["fast", "smart"]] = None  # "fast" (default, gemini-2.5-flash) or "smart" (gemini-2.5-pro)


# ── Quiz ──────────────────────────────────────────────────────────────────────

class GenerateQuizBody(BaseModel):
    question_format: Literal["multiple_choice", "short_answer", "numeric", "symbolic", "mixed"] = "multiple_choice"
    user_id: Id = "user_andres"
    concept_node_id: Id
    # Bounds come from services/quiz_config.py — the same constants
    # GET /api/quiz/config serves, so the client can't offer a value
    # this model rejects (#540 A2).
    num_questions: int = Field(default=5, ge=QUIZ_MIN_QUESTIONS, le=QUIZ_MAX_QUESTIONS)
    difficulty: str = Field(default="medium", max_length=32)
    use_shared_context: bool = True
    # Mirrors the Learn-route fast/smart toggle so quiz generation has
    # the same per-request model-quality choice as chat tutoring.
    # "fast" → gemini-2.5-flash, "smart" → gemini-2.5-pro. None falls
    # through to whatever SAPLING_MODEL_QUIZ resolves to (default
    # gemini-2.5-flash-lite per ADR 0008).
    model_pref: Optional[Literal["fast", "smart"]] = None
    # G5 (#537): "practise the ones you missed" — the attempt whose missed
    # questions should be RE-SERVED verbatim instead of regenerated. The
    # server derives which items those were from that attempt's own
    # `quiz_responses` rows, so the client only has to name the attempt.
    source_attempt_id: Optional[Id] = None
    # Optional override for that derivation: the identities
    # (`services/quiz_identity.py::question_hash`) to re-serve. Hashes are
    # internal — the client projection strips them — so nothing sends this
    # today; it exists for a caller that has already decided which items it
    # wants back. Validated against the source attempt (anything that
    # attempt never held is simply not recoverable), and capped at one
    # quiz's worth, which is the most an attempt can hold.
    missed_question_hashes: Optional[list[Id]] = Field(
        default=None, max_length=QUIZ_MAX_QUESTIONS,
    )
    # DEPRECATED (#541 C3; default flipped false #546 — 2026-08-23).
    #
    # THE canonical account of this flag's lifecycle: every other site that
    # touches it points here rather than restating it, because six copies of
    # this paragraph is six things to update when the flag finally goes.
    #
    # When true, the response's per-option dicts carry `correct` booleans —
    # the full answer key, client-side. The #537 client already grades
    # through POST /api/quiz/attempts/{id}/answer and has sent
    # `include_answer_key: false` on every generate since it shipped, so the
    # flag now defaults to the keyless shape that client has been using all
    # along. The true branch stays accepted for one release for any
    # straggler caller before the parameter itself is deleted.
    #
    # That deletion is gated on telemetry, not on a calendar: every generate
    # that opts in emits `quiz.answer_key_served`, and every one that omits
    # the field entirely emits `quiz.answer_key_flag_omitted`, both countable
    # in the #375 admin-analytics by_event_type rollup. When the served count
    # is zero across a release, the parameter goes. See
    # routes/quiz.py::_record_answer_key_flag for why the two populations get
    # separate event types.
    include_answer_key: bool = False

    @model_validator(mode="after")
    def _hashes_need_a_source(self) -> "GenerateQuizBody":
        """Hashes without a source attempt are a request that cannot mean
        anything: identities are only ever resolved against the named
        attempt's own stored questions, so with no attempt there is nothing
        to resolve them against and every hash would be silently ignored.

        Rejecting says so. Accepting-and-ignoring is how a caller ends up
        debugging why its carefully chosen items were regenerated."""
        if self.missed_question_hashes and not self.source_attempt_id:
            raise ValueError(
                "missed_question_hashes needs a source_attempt_id — hashes are "
                "resolved against that attempt's own questions."
            )
        return self


class AnswerQuestionBody(BaseModel):
    """One answer for POST /api/quiz/attempts/{attempt_id}/answer (#541 C1).

    Indexes are 0-based positions into the attempt's stored questions and
    the question's options. The wire questions carry 1-based `id`s (what
    /submit keys on), so `question_index = id - 1` — two addressing schemes
    for one question. `question_id` is the guard against confusing them:
    send the id you displayed and the route rejects a mismatch instead of
    silently grading the neighbouring question (which the idempotency rule
    would then lock in). The response echoes both either way."""

    question_index: int = Field(ge=0)
    selected_index: Optional[int] = Field(default=None, ge=0)
    answer_text: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    question_id: Optional[int] = None
    time_ms: Optional[int] = Field(default=None, ge=0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def one_answer(self):
        if (self.selected_index is None) == (self.answer_text is None):
            raise ValueError("Supply either an answer choice or a written answer.")
        if self.answer_text is not None and not self.answer_text.strip():
            raise ValueError("The answer must not be blank.")
        return self


class AnswerItem(BaseModel):
    question_id: Union[int, Id]
    selected_label: ShortText


class SubmitQuizBody(BaseModel):
    quiz_id: Id
    answers: list[AnswerItem] = Field(max_length=QUIZ_MAX_QUESTIONS * 4)


# ── Calendar ──────────────────────────────────────────────────────────────────

#: Assignments one save may carry (a syllabus lists far fewer).
ASSIGNMENTS_PER_SAVE_MAX = 500


class AssignmentItem(BaseModel):
    title: str = Field(max_length=500)
    course_id: Id = ""  # Changed from course_name to course_id
    due_date: str = Field(max_length=64)
    assignment_type: str = Field(default="other", max_length=64)
    notes: Optional[str] = Field(default=None, max_length=LONG_TEXT_MAX)


class SaveAssignmentsBody(BaseModel):
    user_id: Id = "user_andres"
    assignments: list[AssignmentItem] = Field(max_length=ASSIGNMENTS_PER_SAVE_MAX)


class StudyBlockBody(BaseModel):
    user_id: Id = "user_andres"


class SyncBody(BaseModel):
    user_id: Id = "user_andres"


class ImportSaveBody(BaseModel):
    """
    Used when the user selects Google Calendar events they want saved
    as Sapling assignments. The frontend maps Google event fields to
    AssignmentItem shape before posting here.
    """
    assignments: list[AssignmentItem] = Field(max_length=ASSIGNMENTS_PER_SAVE_MAX)


class UpdateCalendarAssignmentBody(BaseModel):
    """PATCH /api/calendar/assignments/{id}: the fields a student may change.
    Omitted fields are left alone; ``due_date: ""`` clears the date."""
    user_id: Optional[Id] = None
    title: Optional[str] = Field(default=None, max_length=500)
    due_date: Optional[str] = Field(default=None, max_length=64)
    assignment_type: Optional[str] = Field(default=None, max_length=64)


# ── Graph (Courses) ─────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    """Body for enrolling a user in a course.

    ``course_id`` is the abstract catalog course id; enrollment resolves it to a
    current-term offering (see services/academics.resolve_offering).
    """
    course_id: Id
    color: Optional[str] = Field(default=None, max_length=64)
    nickname: Optional[ShortText] = None


class UpdateCourseColorBody(BaseModel):
    """Body for updating a course enrollment's color."""
    color: str = Field(max_length=64)


# ── Social ────────────────────────────────────────────────────────────────────

class CreateRoomBody(BaseModel):
    user_id: Id = "user_andres"
    room_name: ShortText = "Study Room"
    # #405 semantics: optional labeling + the public flag (false = invite-only).
    topic: ShortText | None = None
    course: ShortText | None = None
    is_public: bool = False


class PublicJoinBody(BaseModel):
    """Body for the invite-less join of a public room (#405)."""
    user_id: Id


class JoinRoomBody(BaseModel):
    user_id: Id = "user_andres"
    invite_code: str = Field(max_length=64)


class MatchBody(BaseModel):
    user_id: Id = "user_andres"


class LeaveRoomBody(BaseModel):
    user_id: Id


# The Supabase Storage bucket the Social chat uploads room images to
# (frontend Social.tsx `supa.storage.from("chat-images")`), and the public-URL
# path its getPublicUrl() returns under the project origin.
ROOM_IMAGE_BUCKET = "chat-images"
_ROOM_IMAGE_PATH_PREFIX = f"/storage/v1/object/public/{ROOM_IMAGE_BUCKET}/"
ROOM_IMAGE_URL_MAX = 2048


def room_image_url_error(url: str) -> Optional[str]:
    """Why ``url`` may not be a room message's image, or None when it may.

    A room's transcript renders every message's ``image_url`` as an <img> for
    every member, so an arbitrary URL is a tracking pixel: each member's
    browser would fetch it (IP, user agent, read time) from wherever the
    sender chose. Only the app's own public room-image bucket on its own
    Supabase project is accepted — exactly what the upload flow produces.
    Read off ``config`` at call time so a test can point it elsewhere; an
    unconfigured ``SUPABASE_URL`` accepts nothing (fail closed).
    """
    import config  # local: models is imported before config in some entry points
    from urllib.parse import urlsplit

    base = (getattr(config, "SUPABASE_URL", "") or "").strip().rstrip("/")
    if not base:
        return "image uploads are not configured"
    if len(url) > ROOM_IMAGE_URL_MAX:
        return "image_url is too long"
    if any(c.isspace() or ord(c) < 0x20 for c in url) or "\\" in url:
        return "image_url must be a room image upload"
    try:
        want = urlsplit(base)
        got = urlsplit(url)
    except ValueError:
        return "image_url must be a room image upload"
    if (
        got.scheme.lower() != want.scheme.lower()
        or got.netloc.lower() != want.netloc.lower()
        or not got.path.startswith(_ROOM_IMAGE_PATH_PREFIX)
        or len(got.path) == len(_ROOM_IMAGE_PATH_PREFIX)
        or any(seg in {"..", "."} for seg in got.path.split("/"))
        or "%2e" in got.path.lower()
        or "%2f" in got.path.lower()
    ):
        return "image_url must be a room image upload"
    return None


class SendMessageBody(BaseModel):
    user_id: Id
    # Ignored: the sender's name is resolved server-side from their profile
    # (services/social/messages.py::send_room_message), so a member cannot post
    # under someone else's name. Still accepted so older clients keep working.
    user_name: Optional[ShortText] = None
    text: Optional[str] = Field(default=None, max_length=ROOM_MESSAGE_MAX)
    image_url: Optional[str] = None

    @field_validator("image_url")
    @classmethod
    def _room_image_only(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        problem = room_image_url_error(v)
        if problem:
            raise ValueError(problem)
        return v
    # Intrinsic pixel size of image_url, measured client-side at upload (#315).
    # Optional: older clients omit them and the UI falls back to unreserved
    # layout, exactly as before.
    #
    # BOUNDED, because these are client-supplied and the transcript renders
    # them as an aspect-ratio directly. Unbounded, any room member could post
    # width=1/height=2000000000 — inside Postgres INTEGER range, so it inserts
    # cleanly — and blow out that room's transcript for everyone, with no edit
    # path to recover. 20000 is comfortably past any real image (8K is 7680)
    # while keeping the ratio sane.
    image_width: Optional[int] = Field(default=None, gt=0, le=20000)
    image_height: Optional[int] = Field(default=None, gt=0, le=20000)
    reply_to_id: Optional[Id] = None


class EditMessageBody(BaseModel):
    user_id: Id
    text: str = Field(max_length=ROOM_MESSAGE_MAX)


class ToggleReactionBody(BaseModel):
    user_id: Id
    # One emoji, which may be several code points (skin tone, ZWJ sequences).
    emoji: str = Field(min_length=1, max_length=32)


class FriendRequestBody(BaseModel):
    from_user_id: Id
    to_user_id: Id


class ExportBody(BaseModel):
    # No default — caller must always supply the real user_id.
    # Prevents accidental exports under the wrong account.
    user_id: Id
    assignment_ids: list[Id] = Field(max_length=ASSIGNMENTS_PER_SAVE_MAX)


# ── Learn (mode switch) ─────────────────────────────────────────────────────

class ModeSwitchBody(BaseModel):
    session_id: Id
    user_id: Id = "user_andres"
    new_mode: TutorMode


# ── Feedback ──────────────────────────────────────────────────────────────────

class SubmitFeedbackBody(BaseModel):
    user_id: Id
    type: Literal["global", "session"]
    rating: int = Field(ge=1, le=5)
    selected_options: list[ShortText] = Field(default_factory=list, max_length=20)
    comment: Optional[LongText] = None
    session_id: Optional[Id] = None
    topic: Optional[ShortText] = None


class SubmitIssueReportBody(BaseModel):
    user_id: Id
    topic: ShortText
    description: LongText
    # The report UI attaches at most 5 (ReportIssueFlow's MAX_SCREENSHOTS).
    screenshot_urls: list[Url] = Field(default_factory=list, max_length=10)


# ── Documents ──────────────────────────────────────────────────────────────────

class UploadDocumentBody(BaseModel):
    """Body for document upload."""
    course_id: Id
    user_id: Id


class UpdateDocumentBody(BaseModel):
    """PATCH /api/documents/doc/{id}. ``category`` stays a bounded string, not
    a Literal, so an unknown one keeps its 400 (the route's contract)."""
    user_id: Optional[Id] = None
    category: Optional[str] = Field(default=None, max_length=64)


class ScanConceptsBody(BaseModel):
    """The two /scan-concepts routes. ``user_id`` is optional here so a
    missing one keeps the route's own 400."""
    user_id: Optional[Id] = None


# ── Onboarding ────────────────────────────────────────────────────────────────

#: The year choices onboarding offers (frontend Onboarding.tsx `YEARS`).
OnboardingYear = Literal["freshman", "sophomore", "junior", "senior", "graduate", "other"]

#: Most courses one onboarding submit may enroll in.
ONBOARDING_MAX_COURSES = 20


class OnboardingBody(BaseModel):
    user_id: Id
    first_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    last_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
    year: OnboardingYear
    # The redesigned onboarding (school -> year + courses) no longer asks for
    # majors or a learning style; both stay accepted for older clients.
    majors: list[ShortText] = Field(default_factory=list, max_length=20)
    minors: list[ShortText] = Field(default_factory=list, max_length=20)
    # Abstract catalog course ids; enrollment resolves each to an offering of
    # the onboarding term. Empty is allowed: "my courses aren't listed — I'll
    # add them later".
    course_ids: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=ONBOARDING_MAX_COURSES,
    )
    learning_style: Optional[str] = Field(default=None, max_length=64)
    # Under-18 students start private: the server applies their privacy
    # settings before onboarding completes (routes/onboarding.py).
    under_18: bool = False
    # The Terms / Privacy Policy versions the student accepted; anything but
    # the current ones (services/legal.py) is a 422 `legal_outdated`.
    accepted_terms_version: ShortText
    accepted_privacy_version: ShortText

    @field_validator("course_ids")
    @classmethod
    def _unique_course_ids(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("course_ids must not repeat a course")
        return v


# ── Profile & Settings ───────────────────────────────────────────────────────

class UpdateProfileBody(BaseModel):
    # Profile fields now live on user_profiles (see migration 0024). `display_name`
    # was a user_settings duplicate of the profile `name` and was dropped; profile
    # name is set during onboarding / OAuth, not via this patch body.
    username: Optional[str] = Field(default=None, max_length=64)
    bio: Optional[str] = Field(default=None, max_length=BIO_MAX)
    location: Optional[ShortText] = None
    website: Optional[str] = None

    @field_validator("website")
    @classmethod
    def _http_website_only(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else normalise_website(v)


PROFILE_WEBSITE_MAX = 512
# A bare host (`example.com`, `example.com/me`), which the Settings field has
# always accepted as typed; it is stored as https.
_BARE_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(?:[/?#]|$)", re.IGNORECASE)


def normalise_website(value: str) -> str:
    """A profile website as stored: "" (cleared) or an absolute http(s) URL.

    The public profile renders it as an ``href`` for every viewer, so a
    ``javascript:`` / ``data:`` / relative value would be a stored XSS or
    open-redirect lure. Raises ValueError (a 422 at the route) for anything
    that is not an http(s) URL with a host, longer than PROFILE_WEBSITE_MAX,
    or carrying whitespace/control characters or credentials.
    """
    from urllib.parse import urlsplit

    v = value.strip()
    if not v:
        return ""
    if len(v) > PROFILE_WEBSITE_MAX:
        raise ValueError(f"website must be at most {PROFILE_WEBSITE_MAX} characters")
    if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F for c in v) or "\\" in v:
        raise ValueError("website must be an http(s) URL")
    if "://" not in v and _BARE_HOST.match(v):
        v = f"https://{v}"
    try:
        parts = urlsplit(v)
        host = parts.hostname
    except ValueError:
        raise ValueError("website must be an http(s) URL")
    if parts.scheme.lower() not in {"http", "https"} or not host or "@" in parts.netloc:
        raise ValueError("website must be an http(s) URL")
    if len(v) > PROFILE_WEBSITE_MAX:
        raise ValueError(f"website must be at most {PROFILE_WEBSITE_MAX} characters")
    return v


class UpdateSettingsBody(BaseModel):
    profile_visibility: Optional[str] = Field(default=None, max_length=32)
    activity_status_visible: Optional[bool] = None
    notification_email: Optional[bool] = None
    notification_push: Optional[bool] = None
    notification_in_app: Optional[bool] = None
    theme: Optional[str] = Field(default=None, max_length=32)
    font_size: Optional[str] = Field(default=None, max_length=32)
    accent_color: Optional[str] = Field(default=None, max_length=64)
    # #72: Class Intel opt-out (user_settings.share_class_context, 0037)
    share_class_context: Optional[bool] = None
    # ADR 0028: third-party (PostHog) analytics opt-out
    # (user_settings.analytics_opt_out) — the student's own choice, written by
    # the Settings → Data switch only. Do Not Track / Global Privacy Control
    # are honoured per request and are deliberately NOT persisted here.
    analytics_opt_out: Optional[bool] = None


class EquipCosmeticBody(BaseModel):
    slot: str = Field(max_length=64)
    cosmetic_id: Optional[Id] = None


class SetFeaturedRoleBody(BaseModel):
    role_id: Optional[Id] = None


class SetFeaturedAchievementsBody(BaseModel):
    achievement_ids: List[Id] = Field(max_length=5)


class DeleteAccountBody(BaseModel):
    confirmation: str = Field(max_length=SHORT_TEXT_MAX)


class AvatarUploadResponse(BaseModel):
    avatar_url: str


class PublicProfileResponse(BaseModel):
    id: str
    name: str
    username: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: Optional[str] = None
    roles: list = []
    featured_achievements: list = []
    equipped_cosmetics: dict = {}
    stats: dict = {}


class SettingsResponse(BaseModel):
    # display_name/username/bio/location/website were dropped from user_settings in
    # migration 0024 (now owned by user_profiles — one source of truth per field).
    user_id: Id
    profile_visibility: str = "public"
    activity_status_visible: bool = True
    notification_email: bool = True
    notification_push: bool = False
    notification_in_app: bool = True
    theme: str = "light"
    font_size: str = "medium"
    accent_color: Optional[str] = None


# ── Roles (Admin) ────────────────────────────────────────────────────────────

class CreateRoleBody(BaseModel):
    name: ShortText
    slug: ShortText
    color: str = Field(max_length=64)
    icon: Optional[Url] = None
    description: Optional[LongText] = None
    is_staff_assigned: bool = True
    is_earnable: bool = False
    display_priority: int = 0


class AssignRoleBody(BaseModel):
    user_id: Id
    role_id: Id


class RevokeRoleBody(BaseModel):
    user_id: Id
    role_id: Id


# ── Achievements (Admin) ─────────────────────────────────────────────────────

class CreateAchievementBody(BaseModel):
    name: ShortText
    slug: ShortText
    description: Optional[LongText] = None
    icon: Optional[Url] = None
    category: ShortText = "milestone"
    rarity: ShortText = "common"
    is_secret: bool = False


class CreateAchievementTriggerBody(BaseModel):
    achievement_id: Id
    trigger_type: ShortText
    trigger_threshold: int


class GrantAchievementBody(BaseModel):
    user_id: Id
    achievement_id: Id


class UpdateAchievementTriggerBody(BaseModel):
    trigger_type: Optional[ShortText] = None
    trigger_threshold: Optional[int] = None


class LinkAchievementCosmeticBody(BaseModel):
    achievement_id: Id
    cosmetic_id: Id


class LinkRoleCosmeticBody(BaseModel):
    role_id: Id
    cosmetic_id: Id


class AchievementIconBody(BaseModel):
    # A 5 MB image is ~6.7 M base64 characters; 8 M leaves room for a data-URL prefix.
    file_base64: str = Field(max_length=8_000_000)
    content_type: str = Field(max_length=100)


class CosmeticAssetBody(BaseModel):
    """An admin cosmetic image, uploaded through the backend (never the
    browser's anon key) before the cosmetic row that points at it exists.
    Capped like AchievementIconBody: the storage helper allows 5 MB."""
    file_base64: str = Field(max_length=8_000_000)
    content_type: str = Field(max_length=100)


class UpdateXpRuleBody(BaseModel):
    amount: Optional[int] = None
    enabled: Optional[bool] = None


# ── Cosmetics (Admin) ────────────────────────────────────────────────────────

class CreateCosmeticBody(BaseModel):
    type: ShortText
    name: ShortText
    slug: ShortText
    asset_url: Optional[Url] = None
    css_value: Optional[str] = Field(default=None, max_length=LONG_TEXT_MAX)
    rarity: ShortText = "common"
    unlock_source: Optional[ShortText] = None


# PATCH bodies for the admin catalog. Every field is optional; the route sends
# only the ones the client set (``model_dump(exclude_unset=True)``) to the
# service, which keeps its own allow-list and its "No valid fields" 400.

class UpdateRoleBody(BaseModel):
    name: Optional[ShortText] = None
    color: Optional[str] = Field(default=None, max_length=64)
    icon: Optional[Url] = None
    description: Optional[LongText] = None
    is_staff_assigned: Optional[bool] = None
    is_earnable: Optional[bool] = None
    display_priority: Optional[int] = Field(default=None, ge=-1_000_000, le=1_000_000)


class UpdateAchievementBody(BaseModel):
    name: Optional[ShortText] = None
    description: Optional[LongText] = None
    icon: Optional[Url] = None
    icon_url: Optional[Url] = None
    category: Optional[ShortText] = None
    rarity: Optional[ShortText] = None
    is_secret: Optional[bool] = None
    xp_reward: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    sort_order: Optional[int] = Field(default=None, ge=-1_000_000, le=1_000_000)
    # The service answers anything but draft/live with its own 422.
    status: Optional[str] = Field(default=None, max_length=32)


class UpdateCosmeticBody(BaseModel):
    name: Optional[ShortText] = None
    asset_url: Optional[Url] = None
    css_value: Optional[str] = Field(default=None, max_length=LONG_TEXT_MAX)
    rarity: Optional[ShortText] = None
    unlock_source: Optional[ShortText] = None


# ── Gradebook ────────────────────────────────────────────────────────────────

# Enrollment / gradebook key on the abstract course_id + an optional `semester`
# (a term label, e.g. "Spring 2026"; default = current term). The route maps
# (course_id, semester) -> the user's enrollment via services.academics.
AssignmentType = Literal["homework", "exam", "reading", "project", "quiz", "other"]


class CategoryItem(BaseModel):
    id: Optional[Id] = None              # null on create
    name: ShortText
    weight: float = Field(ge=0, le=100)
    sort_order: int = 0
    drop_lowest: int = Field(default=0, ge=0)  # gradebook_categories.drop_lowest


class CreateCategoryBody(BaseModel):
    user_id: Id
    semester: Optional[ShortText] = None        # term label; default = current term
    name: ShortText
    weight: float = Field(ge=0, le=100)
    drop_lowest: int = Field(default=0, ge=0)


class BulkUpdateCategoriesBody(BaseModel):
    user_id: Id
    semester: Optional[ShortText] = None
    categories: list[CategoryItem] = Field(max_length=100)  # full replacement set


class CreateAssignmentBody(BaseModel):
    user_id: Id
    course_id: Id
    semester: Optional[ShortText] = None
    title: str = Field(max_length=500)
    category_id: Optional[Id] = None
    points_possible: Optional[float] = Field(default=None, gt=0)
    points_earned: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = Field(default=None, max_length=64)
    assignment_type: Optional[AssignmentType] = None
    notes: Optional[LongText] = None
    curve_class_mean: Optional[float] = Field(default=None, ge=0, le=1)
    curve_class_sd: Optional[float] = Field(default=None, ge=0, le=1)
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)


class UpdateAssignmentBody(BaseModel):
    user_id: Id
    title: Optional[str] = Field(default=None, max_length=500)
    category_id: Optional[Id] = None
    points_possible: Optional[float] = Field(default=None, gt=0)
    points_earned: Optional[float] = Field(default=None, ge=0)
    due_date: Optional[str] = Field(default=None, max_length=64)
    assignment_type: Optional[AssignmentType] = None
    notes: Optional[LongText] = None
    curve_class_mean: Optional[float] = Field(default=None, ge=0, le=1)
    curve_class_sd: Optional[float] = Field(default=None, ge=0, le=1)
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)


class CurveSettingsBody(BaseModel):
    user_id: Id
    curve_mode: Literal["raw", "curved"] = "raw"
    curve_avg_target: Optional[float] = Field(default=None, ge=0, le=1)
    curve_sd_delta: Optional[float] = Field(default=None, ge=0, le=1)


class LetterScaleTier(BaseModel):
    min: float = Field(ge=0, le=100)
    letter: str = Field(max_length=8)


class SetLetterScaleBody(BaseModel):
    user_id: Id
    semester: Optional[ShortText] = None
    scale: Optional[list[LetterScaleTier]] = Field(default=None, max_length=50)  # null clears the override


class SetCurveBody(BaseModel):
    """Per-enrollment bell-curve policy (enrollments.curve_*)."""
    user_id: Id
    semester: Optional[ShortText] = None
    curve_mode: Literal["raw", "curved"] = "raw"
    curve_avg_target: Optional[float] = None
    curve_sd_delta: Optional[float] = None


class SyllabusApplyBody(BaseModel):
    user_id: Id
    course_id: Id
    semester: Optional[ShortText] = None
    doc_id: Id
    categories: list[CategoryItem] = Field(max_length=100)
    assignments: list[dict] = Field(max_length=ASSIGNMENTS_PER_SAVE_MAX)            # uses the same shape as syllabus extraction


# ── Newsletter & Allowlist (Admin) ──────────────────────────────────────────

class AllowlistEmailBody(BaseModel):
    """POST /api/admin/allowlist/{approve,revoke}. Lowercased and stripped the
    way the bulk path normalises (#757): the waitlist keeps emails as typed, so
    a raw spelling would miss (or twin) the row sign-in matches."""
    email: str

    @field_validator("email")
    @classmethod
    def _normalize(cls, v: str) -> str:
        email = (v or "").strip().lower()
        if not email or len(email) > 254 or not _EMAIL_SHAPE.match(email):
            raise ValueError("invalid email address")
        return email


# One address, no spaces, a dot in the domain. Deliberately loose (the waitlist
# signup already validated with EmailStr); it only has to stop pasted junk.
_EMAIL_SHAPE = re.compile(r"^[^@\s,;<>()\"]+@[^@\s,;<>()\"]+\.[^@\s,;<>()\"]+$")
ALLOWLIST_BULK_MAX = 500


class AllowlistBulkBody(BaseModel):
    """POST /api/admin/allowlist/approve-bulk. Lowercased, stripped, deduped
    (first occurrence wins), 1..500 addresses."""
    emails: list[str] = Field(min_length=1, max_length=ALLOWLIST_BULK_MAX)

    @field_validator("emails")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        bad: list[str] = []
        for raw in v:
            email = (raw or "").strip().lower()
            if not email or len(email) > 254 or not _EMAIL_SHAPE.match(email):
                bad.append(raw)
                continue
            seen.setdefault(email, None)
        if bad:
            raise ValueError(f"invalid email address(es): {', '.join(map(str, bad[:5]))}")
        if not seen:
            raise ValueError("at least one email is required")
        return list(seen)


EMAIL_AUDIENCES = (
    "waitlist_all",
    "waitlist_pending",
    "waitlist_approved_not_joined",
    "users_all",
)


class EmailBroadcastTestBody(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("subject", "body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("subject")
    @classmethod
    def _one_line(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("subject", "body")
    @classmethod
    def _known_variables(cls, v: str) -> str:
        # Never mail out literal {{braces}}: a typo'd variable is a 422.
        from services.email_variables import unknown_variables, unknown_variables_message
        unknown = unknown_variables(v)
        if unknown:
            raise ValueError(unknown_variables_message(unknown))
        return v


class EmailBroadcastPreviewBody(BaseModel):
    """A draft as it's being typed: blank is fine, it just previews empty."""
    subject: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=20000)


class EmailBroadcastBody(EmailBroadcastTestBody):
    audience: Literal[
        "waitlist_all",
        "waitlist_pending",
        "waitlist_approved_not_joined",
        "users_all",
    ]
