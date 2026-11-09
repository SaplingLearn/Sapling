"""Moved to services/quiz/repetition.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_repetition.<name>")`
both land on the real one. New code imports services.quiz.repetition."""
import sys

from services.quiz import repetition

sys.modules[__name__] = repetition
