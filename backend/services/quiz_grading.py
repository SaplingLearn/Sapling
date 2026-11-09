"""Moved to services/quiz/grading.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_grading.<name>")`
both land on the real one. New code imports services.quiz.grading."""
import sys

from services.quiz import grading

sys.modules[__name__] = grading
