"""Moved to services/quiz/algebra.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_algebra.<name>")`
both land on the real one. New code imports services.quiz.algebra."""
import sys

from services.quiz import algebra

sys.modules[__name__] = algebra
