from typing import Optional, Union
from pydantic import BaseModel


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
