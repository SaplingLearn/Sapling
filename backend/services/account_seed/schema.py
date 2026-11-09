"""Content model for one major's seed pack (admin "seed account" tool).

A pack is pure, static, hand-authored content: no ids, no dates, no catalog
UUIDs. `seeder.py` turns it into rows for one account on whatever environment
it runs in — resolving courses by `code`, offerings in the current term, and
dates as day offsets from that term's `start_date`. Keeping the pack free of
environment facts is what lets the same pack seed local, staging and prod.

Validation here is the contract every pack is tested against
(tests/test_account_seed_packs.py), so a malformed pack fails CI, not an
admin's click on prod.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

AssignmentType = Literal["homework", "exam", "quiz", "project", "reading", "other"]  # DB CHECK (0021)
RelationshipType = Literal["prerequisite", "builds_on", "related", "part_of"]
DocumentCategory = Literal["syllabus", "lecture_notes", "study_guide", "reading", "slides"]
SessionMode = Literal["socratic", "expository"]


class Concept(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    #: 0..1 — the seeder derives the tier with learning.bkt.tier_for (the one
    #: score -> tier map, spec §3.1).
    mastery: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=10, max_length=300)


class Edge(BaseModel):
    source: str  # Concept.name in the same course
    target: str  # Concept.name in the same course
    relationship: RelationshipType
    strength: float = Field(ge=0.0, le=1.0)


class MasteryEvent(BaseModel):
    concept: str  # Concept.name
    delta: float = Field(ge=-1.0, le=1.0)
    reason: str = Field(min_length=3, max_length=80)


class Category(BaseModel):
    name: str
    weight: float = Field(gt=0.0, le=1.0)
    drop_lowest: int = Field(default=0, ge=0, le=3)


class Assignment(BaseModel):
    title: str
    category: str  # Category.name in the same course
    type: AssignmentType
    #: Days after the current term's start_date. The seeder grades only
    #: assignments whose due date is already past on seed day, so "earned"
    #: on a future item is ignored (it stays upcoming/ungraded).
    due_offset_days: int = Field(ge=0, le=130)
    points_possible: float = Field(gt=0)
    points_earned: float | None = None
    is_midterm: bool = False  # the study guide targets this one

    @model_validator(mode="after")
    def _earned_le_possible(self):
        if self.points_earned is not None and not 0 <= self.points_earned <= self.points_possible:
            raise ValueError(f"{self.title}: points_earned out of range")
        return self


class Note(BaseModel):
    title: str
    body: str = Field(min_length=80)  # markdown allowed
    tags: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)  # Concept.names to link


class ConceptNote(BaseModel):
    name: str
    description: str


class Document(BaseModel):
    file_name: str  # e.g. "cs111-syllabus.pdf"
    category: DocumentCategory
    summary: str = Field(min_length=40)
    concept_notes: list[ConceptNote] = Field(min_length=1)
    extracted_text: str = Field(min_length=400)  # ~150-300 words of "OCR" text


class Flashcard(BaseModel):
    front: str
    back: str


class StudyGuideTopic(BaseModel):
    name: str
    importance: str
    concepts: list[str] = Field(min_length=1)


class StudyGuide(BaseModel):
    overview: str
    topics: list[StudyGuideTopic] = Field(min_length=2)


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_answer: str  # must be one of options, verbatim
    explanation: str

    @model_validator(mode="after")
    def _answer_in_options(self):
        if self.correct_answer not in self.options:
            raise ValueError(f"correct_answer not in options: {self.question!r}")
        return self


class QuizAttempt(BaseModel):
    concept: str  # Concept.name
    difficulty: Literal["easy", "medium", "hard"]
    days_ago: int = Field(ge=0, le=60)
    questions: list[QuizQuestion] = Field(min_length=3, max_length=5)
    #: Indexes into `questions` the student got right.
    correct: list[int]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class TutorSession(BaseModel):
    name: str
    topic: str  # usually a Concept.name
    mode: SessionMode
    summary_bullets: list[str] = Field(min_length=2, max_length=5)
    messages: list[ChatMessage] = Field(min_length=4, max_length=8)


class Course(BaseModel):
    code: str  # catalog course_code, e.g. "CAS CS 111"
    name: str  # fallback course_name if the catalog lacks the code
    department: str
    credits: int = Field(default=4, ge=1, le=6)
    nickname: str = Field(max_length=24)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    concepts: list[Concept] = Field(min_length=8, max_length=10)
    edges: list[Edge] = Field(min_length=5)
    mastery_events: list[MasteryEvent] = Field(min_length=2)
    categories: list[Category] = Field(min_length=2, max_length=4)
    assignments: list[Assignment] = Field(min_length=6, max_length=8)
    notes: list[Note] = Field(min_length=2, max_length=3)
    documents: list[Document] = Field(min_length=2, max_length=3)
    flashcards: list[Flashcard] = Field(min_length=6, max_length=10)
    study_guide: StudyGuide
    quizzes: list[QuizAttempt] = Field(min_length=2, max_length=3)
    session: TutorSession

    @model_validator(mode="after")
    def _references_resolve(self):
        names = {c.name for c in self.concepts}
        if len(names) != len(self.concepts):
            raise ValueError(f"{self.code}: duplicate concept names")
        cats = {c.name for c in self.categories}
        problems: list[str] = []
        problems += [f"edge {e.source}->{e.target}" for e in self.edges
                     if e.source not in names or e.target not in names or e.source == e.target]
        problems += [f"mastery event {m.concept}" for m in self.mastery_events if m.concept not in names]
        problems += [f"assignment category {a.category}" for a in self.assignments if a.category not in cats]
        problems += [f"note concept {c}" for n in self.notes for c in n.concepts if c not in names]
        problems += [f"quiz concept {q.concept}" for q in self.quizzes if q.concept not in names]
        problems += [f"quiz correct index {i}" for q in self.quizzes for i in q.correct
                     if not 0 <= i < len(q.questions)]
        if sum(1 for a in self.assignments if a.is_midterm) != 1:
            problems.append("exactly one assignment must be is_midterm")
        if abs(sum(c.weight for c in self.categories) - 1.0) > 1e-6:
            problems.append("category weights must sum to 1.0")
        tiers = {_tier(c.mastery) for c in self.concepts}
        if len(tiers) < 4:
            problems.append(f"concept mastery must span all four tiers (got {sorted(tiers)})")
        if problems:
            raise ValueError(f"{self.code}: unresolved/invalid: {', '.join(problems)}")
        return self


class MajorPack(BaseModel):
    key: str = Field(pattern=r"^[a-z_]+$")  # "cs", "business", ...
    label: str  # "Computer Science" — written to user_profiles.majors
    year: str = "Sophomore"
    courses: list[Course] = Field(min_length=4, max_length=4)
    #: Account-level gamification.
    total_xp: int = Field(default=1250, ge=0)
    streak_days: int = Field(default=6, ge=0)

    @model_validator(mode="after")
    def _unique_codes(self):
        codes = [c.code for c in self.courses]
        if len(set(codes)) != len(codes):
            raise ValueError(f"{self.key}: duplicate course codes")
        return self


def _tier(score: float) -> str:
    # The seeder writes mastery_tier with this same function, so "spans all
    # four tiers" is checked against exactly what the graph will show.
    from learning.bkt import tier_for

    return tier_for(score)
