from typing import Optional, Union, List
from pydantic import BaseModel, Field


# ── Learn ─────────────────────────────────────────────────────────────────────

class StartSessionBody(BaseModel):
    user_id: str = "user_andres"
    topic: str = ""
    mode: str = "socratic"
    use_shared_context: bool = True
    course_id: Optional[str] = None  # Direct course_id lookup instead of resolving from topic


class ChatBody(BaseModel):
    session_id: str
    user_id: str = "user_andres"
    message: str
    mode: str = "socratic"
    use_shared_context: bool = True


class EndSessionBody(BaseModel):
    session_id: str
    user_id: str = ""  # Required to discard a lazy (not-yet-persisted) session safely


class ActionBody(BaseModel):
    session_id: str
    user_id: str = "user_andres"
    action_type: str = "hint"
    mode: str = "socratic"
    use_shared_context: bool = True


# ── Quiz ──────────────────────────────────────────────────────────────────────

class GenerateQuizBody(BaseModel):
    user_id: str = "user_andres"
    concept_node_id: str
    num_questions: int = 5
    difficulty: str = "medium"
    use_shared_context: bool = True


class AnswerItem(BaseModel):
    question_id: Union[int, str]
    selected_label: str


class SubmitQuizBody(BaseModel):
    quiz_id: str
    answers: list[AnswerItem]


# ── Calendar ──────────────────────────────────────────────────────────────────

class AssignmentItem(BaseModel):
    title: str
    course_id: str = ""  # Changed from course_name to course_id
    due_date: str
    assignment_type: str = "other"
    notes: Optional[str] = None


class SaveAssignmentsBody(BaseModel):
    user_id: str = "user_andres"
    assignments: list[AssignmentItem]


class StudyBlockBody(BaseModel):
    user_id: str = "user_andres"


class SyncBody(BaseModel):
    user_id: str = "user_andres"


class ImportSaveBody(BaseModel):
    """
    Used when the user selects Google Calendar events they want saved
    as Sapling assignments. The frontend maps Google event fields to
    AssignmentItem shape before posting here.
    """
    assignments: list[AssignmentItem]


# ── Graph (Courses) ─────────────────────────────────────────────────────────

class AddCourseBody(BaseModel):
    """Body for enrolling a user in a course (creating a user_courses record)."""
    course_id: str
    color: Optional[str] = None
    nickname: Optional[str] = None


class UpdateCourseColorBody(BaseModel):
    """Body for updating a course enrollment's color."""
    color: str


# ── Social ────────────────────────────────────────────────────────────────────

class CreateRoomBody(BaseModel):
    user_id: str = "user_andres"
    room_name: str = "Study Room"


class JoinRoomBody(BaseModel):
    user_id: str = "user_andres"
    invite_code: str


class MatchBody(BaseModel):
    user_id: str = "user_andres"


class LeaveRoomBody(BaseModel):
    user_id: str


class SendMessageBody(BaseModel):
    user_id: str
    user_name: str
    text: Optional[str] = None
    image_url: Optional[str] = None
    reply_to_id: Optional[str] = None


class EditMessageBody(BaseModel):
    user_id: str
    text: str


class ToggleReactionBody(BaseModel):
    user_id: str
    emoji: str


class ExportBody(BaseModel):
    # No default — caller must always supply the real user_id.
    # Prevents accidental exports under the wrong account.
    user_id: str
    assignment_ids: list[str]


# ── Learn (mode switch) ─────────────────────────────────────────────────────

class ModeSwitchBody(BaseModel):
    session_id: str
    user_id: str = "user_andres"
    new_mode: str


# ── Feedback ──────────────────────────────────────────────────────────────────

class SubmitFeedbackBody(BaseModel):
    user_id: str
    type: str  # 'global' | 'session'
    rating: int
    selected_options: list[str] = []
    comment: Optional[str] = None
    session_id: Optional[str] = None
    topic: Optional[str] = None


class SubmitIssueReportBody(BaseModel):
    user_id: str
    topic: str
    description: str
    screenshot_urls: list[str] = []


# ── Documents ──────────────────────────────────────────────────────────────────

class UploadDocumentBody(BaseModel):
    """Body for document upload."""
    course_id: str
    user_id: str


# ── Onboarding ────────────────────────────────────────────────────────────────

class OnboardingBody(BaseModel):
    user_id: str
    first_name: str
    last_name: str
    year: str
    majors: list[str] = Field(min_length=1)
    minors: list[str] = []
    course_ids: list[str] = Field(min_length=1)
    learning_style: str


# ── Profile & Settings ───────────────────────────────────────────────────────

class UpdateProfileBody(BaseModel):
    username: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    display_name: Optional[str] = None


class UpdateSettingsBody(BaseModel):
    profile_visibility: Optional[str] = None
    activity_status_visible: Optional[bool] = None
    notification_email: Optional[bool] = None
    notification_push: Optional[bool] = None
    notification_in_app: Optional[bool] = None
    theme: Optional[str] = None
    font_size: Optional[str] = None
    accent_color: Optional[str] = None


class EquipCosmeticBody(BaseModel):
    slot: str
    cosmetic_id: Optional[str] = None


class SetFeaturedRoleBody(BaseModel):
    role_id: Optional[str] = None


class SetFeaturedAchievementsBody(BaseModel):
    achievement_ids: List[str] = Field(max_length=5)


class DeleteAccountBody(BaseModel):
    confirmation: str


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
    user_id: str
    display_name: Optional[str] = None
    username: Optional[str] = None
    bio: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
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
    name: str
    slug: str
    color: str
    icon: Optional[str] = None
    description: Optional[str] = None
    is_staff_assigned: bool = True
    is_earnable: bool = False
    display_priority: int = 0


class AssignRoleBody(BaseModel):
    user_id: str
    role_id: str
    granted_by: Optional[str] = None


class RevokeRoleBody(BaseModel):
    user_id: str
    role_id: str


# ── Achievements (Admin) ─────────────────────────────────────────────────────

class CreateAchievementBody(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = None
    category: str = "milestone"
    rarity: str = "common"
    is_secret: bool = False


class CreateAchievementTriggerBody(BaseModel):
    achievement_id: str
    trigger_type: str
    trigger_threshold: int


class GrantAchievementBody(BaseModel):
    user_id: str
    achievement_id: str


# ── Cosmetics (Admin) ────────────────────────────────────────────────────────

class CreateCosmeticBody(BaseModel):
    type: str
    name: str
    slug: str
    asset_url: Optional[str] = None
    css_value: Optional[str] = None
    rarity: str = "common"
    unlock_source: Optional[str] = None
