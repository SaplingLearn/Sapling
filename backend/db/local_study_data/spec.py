"""The shapes the local study dataset is written in.

One ``ClassData`` per class (``cs101.py``, ``math210.py``, ``bio110.py``; a
class's section drafts and guides are in its ``_guides`` module).
Everything in it is plain data: names, text, and whole numbers of days
relative to the day the seed runs. Rows are made from it by the builder
modules beside this one; nothing here knows about ids or the database.

Things refer to each other by short keys: a concept by its ``key``, a document
by its ``key``, an exam or assignment by its ``key``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from models.study_guide import ProseItem

#: How long a guide section can be, shortest first. A guide's depth names the
#: length of its sections, and a concept the student has mastered gets the
#: length below it (``brief`` is a mastered section of a cram guide).
LENGTHS = ("brief", "cram", "standard", "deep")


@dataclass(frozen=True)
class Concept:
    key: str
    #: The name on the student's tree. Guides, flashcard decks and the outline
    #: all join on it.
    name: str
    #: The outline unit it sits under: a roadmap column on the Study hub.
    unit: str
    #: One sentence. Used as the document concept note, the key term and the
    #: outline description.
    definition: str
    #: Mastery, 0 to 1.
    score: float
    times_studied: int = 0
    #: Days since it was last studied; None when it never was.
    last_studied: int | None = None
    #: Keys of the concepts needed first.
    needs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Material:
    """One uploaded document."""

    key: str
    file_name: str
    category: str
    #: Days before today it was uploaded.
    days_ago: int
    summary: str
    #: Keys of the concepts it teaches.
    concepts: tuple[str, ...]
    #: The extracted text, one string per paragraph.
    text: tuple[str, ...]


@dataclass(frozen=True)
class Assessment:
    """One row of the class's dated work."""

    key: str
    title: str
    #: ``assignments.assignment_type``.
    kind: str
    #: Days from today; negative when it is already past.
    in_days: int
    points: int = 100
    #: None until it is graded.
    earned: int | None = None
    #: The outline units an exam covers (what its readiness band speaks for).
    covers: tuple[str, ...] = ()
    #: Keys of single concepts it covers, for a quiz narrower than a unit.
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Quiz:
    """One quiz attempt on a concept. Its questions are made from the
    concept's flashcards."""

    concept: str
    days_ago: int
    #: Local clock hour it was finished at, on an earlier day.
    hour: int
    correct: int
    total: int = 5
    difficulty: str = "medium"
    #: How long it took.
    minutes: int = 7
    #: ``done``, ``open`` (started, some answers in) or ``abandoned``.
    state: str = "done"
    #: For a quiz taken today: how long ago it was finished.
    minutes_ago: int = 50


@dataclass(frozen=True)
class Digest:
    """What the quiz history recorded about one concept
    (``quiz_context.context_json``)."""

    concept: str
    common_mistakes: tuple[str, ...]
    weak_areas: tuple[str, ...] = ()
    seen: str = ""
    difficulty: str = "medium"


@dataclass(frozen=True)
class Tutoring:
    """One tutor session on a concept."""

    key: str
    concept: str
    name: str
    days_ago: int
    hour: int
    #: Minutes into the session of each message. Study time is read from them.
    beats: tuple[int, ...]
    mode: str = "socratic"
    ended: bool = False


@dataclass(frozen=True)
class CardSet:
    """A saved flashcard set."""

    key: str
    name: str
    concepts: tuple[str, ...]
    days_ago: int
    #: Key of the exam it was made for.
    exam: str | None = None
    only_due: bool = False
    shuffle: bool = True


@dataclass(frozen=True)
class Passage:
    """One prose passage of a section draft. ``at`` is the shortest length of
    the section that has it: a ``standard`` passage is in a standard and a
    deep section and is left out of a cram one."""

    item: ProseItem
    at: str = "cram"


@dataclass(frozen=True)
class SectionDraft:
    """One guide section as written: its title, its one-line essence and its
    items in reading order (``blocks.py`` makes them): passages, each for a
    length, and blocks, which every length keeps. A guide picks drafts by
    concept key."""

    title: str
    one_line: str
    items: tuple


@dataclass(frozen=True)
class GuideSpec:
    key: str
    title: str
    deck: str
    takeaways: tuple[str, ...]
    #: Key of the exam or assignment it is for; None for the whole course.
    scope: str | None
    goal: str
    depth: str
    #: Concept keys, in section order.
    sections: tuple[str, ...]
    #: Hours before now it was generated (and made).
    made_hours_ago: int
    saved_hours_ago: int | None = None
    use_history: bool = True
    #: Still being written: every section is queued and nothing is dated.
    generating: bool = False
    #: Concept keys of sections the writer could not write.
    failed: tuple[str, ...] = ()
    #: Concept keys of sections marked read.
    read: tuple[str, ...] = ()
    #: Concept key to the option letter picked on that section's check.
    answers: dict[str, str] = field(default_factory=dict)
    feedback: str | None = None


@dataclass(frozen=True)
class LegacyGuide:
    """A guide from before the redesign: ``{exam, due_date, overview,
    topics}``, stored as format 1 and upgraded when read."""

    key: str
    scope: str
    made_hours_ago: int
    overview: str
    #: (name, why it matters, concept bullets) per topic.
    topics: tuple[tuple[str, str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class ClassData:
    key: str
    #: The abstract course (``courses.id``) the rich seed enrolls the account in.
    course_id: str
    concepts: tuple[Concept, ...]
    materials: tuple[Material, ...]
    assessments: tuple[Assessment, ...]
    #: Concept key to its flashcards, as (front, back).
    cards: dict[str, tuple[tuple[str, str], ...]]
    quizzes: tuple[Quiz, ...]
    digests: tuple[Digest, ...]
    tutoring: tuple[Tutoring, ...]
    card_sets: tuple[CardSet, ...]
    #: Concept key to the section written about it.
    sections: dict[str, SectionDraft]
    guides: tuple[GuideSpec, ...]
    legacy_guides: tuple[LegacyGuide, ...] = ()
    #: Exams and quizzes the account may already have in the class (the rich
    #: seed's), by title, to the keys of the concepts each covers.
    earlier_exams: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def concept(self, key: str) -> Concept:
        return next(c for c in self.concepts if c.key == key)

    def material(self, key: str) -> Material:
        return next(m for m in self.materials if m.key == key)

    def assessment(self, key: str) -> Assessment:
        return next(a for a in self.assessments if a.key == key)

    def digest(self, concept_key: str) -> Digest | None:
        return next((d for d in self.digests if d.concept == concept_key), None)
