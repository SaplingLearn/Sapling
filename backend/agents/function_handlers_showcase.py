"""Showcase FunctionModel handlers for the /gallery product screenshots.

Importing this module registers per-task handlers on the #391 seam. It loads
ONLY when the backend boots with

    SAPLING_MODEL_MODE=function
    SAPLING_FUNCTION_HANDLERS=agents.function_handlers_showcase

which is what `scripts/gallery-shots.sh` does. Production, the hermetic pytest
lane and the E2E browser lane never import it.

`function_handlers_e2e.py` says journeys for new tasks should append there
rather than growing parallel modules, and that is right — for journeys. This
is not one. Those constants are asserted verbatim by the Chapter 1 specs and
by tests/test_e2e_function_handlers.py, so they cannot be rewritten to read
well in a marketing screenshot, and a screenshot cannot show
"[e2e-function-model] Deterministic tutor reply". The two modules want
opposite things from the same seam: one wants strings a test can pin, the
other wants prose a person can read. Hence the fork. Nothing imports across
it — importing the E2E module here would register ITS handlers as a side
effect and quietly win.

Copy here tracks the rich local seed (db/seed_local_rich.py), because the
screenshots show both at once: the graph node the tutor is talking about is a
seeded row, so a handler that discussed some other topic would photograph an
incoherent screen. CS101 · Recursion is the through-line, matching the seeded
struggling concept.

Same constraints as the E2E module: fixed output, no model-driven tool calls.
LOCAL ONLY.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from agents._providers import FunctionModelHandler, register_function_handler


def _structured_output(args: dict) -> FunctionModelHandler:
    """Emit `args` through the agent's registered output tool, so the REAL
    output schema validates the payload before the agent returns.

    Deliberately a local copy of the E2E module's helper rather than an import:
    importing that module to borrow one function would run its registrations.
    """

    def handler(messages, info) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)]
        )

    return handler


# ── Tutor (/learn) ──────────────────────────────────────────────────────────
#
# Socratic mode: the tutor asks before it tells, which is the product's whole
# stance and the thing a screenshot of the tutor should be showing.

SHOWCASE_TUTOR_REPLY = (
    "Before I answer that — walk me through what happens on the very first "
    "call. When `factorial(4)` runs, what does it need from `factorial(3)` "
    "before it can return anything?\n\n"
    "That dependency is the part worth getting solid. Once you can say out "
    "loud what each call is waiting on, the base case stops looking like a "
    "rule you memorised and starts looking like the only way the stack ever "
    "unwinds."
)


def _chat_tutor_handler(messages, info) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=SHOWCASE_TUTOR_REPLY)])


register_function_handler("chat_tutor", _chat_tutor_handler)


# ── Quiz (/quiz) ────────────────────────────────────────────────────────────
#
# Three questions on the seeded CS101 concepts, written so the screenshot
# shows a real question a student would recognise from the course.

_SHOWCASE_QUIZ_QUESTIONS = [
    {
        "question": (
            "A recursive function computes the sum of a list by adding the "
            "first element to the sum of the rest. What happens if the base "
            "case is removed?"
        ),
        "type": "multiple_choice",
        "difficulty": "medium",
        "options": [
            "It returns 0 for every input",
            "It recurses until the call stack overflows",
            "It returns only the first element",
            "It silently skips the last element",
        ],
        "correct_answer": "It recurses until the call stack overflows",
        "explanation": (
            "Without a base case nothing stops the descent: each call makes "
            "another call on a shorter list, and the empty list never returns "
            "a value. The stack grows until the runtime gives up."
        ),
        "concept": "Recursion",
    },
    {
        "question": (
            "Which of these problems is a natural fit for recursion rather "
            "than a simple loop?"
        ),
        "type": "multiple_choice",
        "difficulty": "easy",
        "options": [
            "Summing the integers from 1 to n",
            "Finding the largest value in a flat array",
            "Walking every node of a binary tree",
            "Counting the characters in a string",
        ],
        "correct_answer": "Walking every node of a binary tree",
        "explanation": (
            "A tree is defined in terms of itself — each child is a tree — so "
            "the traversal mirrors the structure. The other three are flat "
            "sequences a loop handles more directly."
        ),
        "concept": "Recursion",
    },
    {
        "question": (
            "In a recursive call, what is actually stored on the call stack "
            "for each pending invocation?"
        ),
        "type": "multiple_choice",
        "difficulty": "hard",
        "options": [
            "Only the return value",
            "The function's local state and where to resume",
            "A copy of the entire program",
            "Nothing — recursion reuses one frame",
        ],
        "correct_answer": "The function's local state and where to resume",
        "explanation": (
            "Each call gets its own frame holding its arguments, locals and "
            "the return address. That is why deep recursion costs memory, and "
            "why an unbounded descent overflows."
        ),
        "concept": "Recursion",
    },
]


def _quiz_handler(messages, info) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"questions": _SHOWCASE_QUIZ_QUESTIONS},
            )
        ]
    )


register_function_handler("quiz", _quiz_handler)


# ── Document pipeline (/library) ────────────────────────────────────────────

SHOWCASE_DOC_CATEGORY = "lecture_notes"
SHOWCASE_DOC_HEADLINE = "Recursion, the call stack, and when to reach for it"
SHOWCASE_DOC_ABSTRACT = (
    "Lecture notes covering recursive problem decomposition: how a function "
    "expressed in terms of itself terminates, what each pending call costs on "
    "the stack, and the tree and divide-and-conquer shapes where recursion "
    "reads more clearly than iteration."
)
SHOWCASE_DOC_KEY_POINTS = [
    "Every recursive definition needs a base case that returns without recursing.",
    "Each pending call holds its own frame, so depth costs memory.",
    "Tree traversal and divide-and-conquer mirror the recursive structure.",
    "Tail calls can be rewritten as loops when depth is a concern.",
]
# (name, description, importance)
SHOWCASE_DOC_CONCEPTS = [
    ("Recursion", "A function defined in terms of a smaller call to itself.", 0.9),
    ("Base Case", "The condition that returns without recursing, ending the descent.", 0.8),
    ("Call Stack", "The frames holding each pending call's locals and return address.", 0.7),
]

register_function_handler(
    "classifier",
    _structured_output({
        "category": SHOWCASE_DOC_CATEGORY,
        "is_syllabus": False,
        "confidence": 0.96,
        "rationale": "Narrative lecture notes with worked examples; no schedule or grading table.",
    }),
)
register_function_handler(
    "summary",
    _structured_output({
        "headline": SHOWCASE_DOC_HEADLINE,
        "abstract": SHOWCASE_DOC_ABSTRACT,
        "key_points": SHOWCASE_DOC_KEY_POINTS,
    }),
)
register_function_handler(
    "concepts",
    _structured_output({
        "concepts": [
            {"name": name, "description": desc, "importance": imp}
            for name, desc, imp in SHOWCASE_DOC_CONCEPTS
        ],
    }),
)
register_function_handler(
    "course_summary",
    _structured_output({
        "summary": (
            "Strong on variables and algorithms, steady on control flow. "
            "Recursion is the concept holding the rest back — the notes and "
            "quiz results both point at the base case."
        ),
    }),
)


# ── Concept blurb (/tree) ───────────────────────────────────────────────────

SHOWCASE_CONCEPT_DESCRIPTION = (
    "A function that solves a problem by calling itself on a smaller piece of "
    "it, stopping at a base case simple enough to answer outright. Feeds "
    "tree traversal and divide-and-conquer."
)

register_function_handler(
    "concept_describe",
    _structured_output({"description": SHOWCASE_CONCEPT_DESCRIPTION}),
)

SHOWCASE_SCAN_NEW_CONCEPTS = ["Tail Recursion", "Stack Frames"]

register_function_handler(
    "concept_scan",
    _structured_output({"concepts": SHOWCASE_SCAN_NEW_CONCEPTS}),
)


# ── Notetaker (/notetaker) ──────────────────────────────────────────────────

SHOWCASE_NOTE_SUMMARY = (
    "The note works through recursion as self-reference with a stopping "
    "condition, using `factorial` and a list sum as the worked examples. The "
    "open question at the end — why the base case has to return a value "
    "rather than just stop — is the thread worth picking up next."
)
SHOWCASE_NOTE_CONCEPTS = ["Recursion", "Base Case", "Call Stack"]
SHOWCASE_NOTE_CHAT_REPLY = (
    "Your note has the shape right. The bit still missing is what the base "
    "case hands back: it has to return a real value, because every call above "
    "it is waiting to add something to that result."
)


def _note_chat_handler(messages, info) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=SHOWCASE_NOTE_CHAT_REPLY)])


register_function_handler(
    "note_summary", _structured_output({"summary": SHOWCASE_NOTE_SUMMARY})
)
register_function_handler(
    "note_concepts", _structured_output({"concepts": SHOWCASE_NOTE_CONCEPTS})
)
register_function_handler("note_chat", _note_chat_handler)
