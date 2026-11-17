"""Moved to services/quiz/distractors.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_distractors.<name>")`
both land on the real one. New code imports services.quiz.distractors."""
import sys

from services.quiz import distractors

sys.modules[__name__] = distractors
