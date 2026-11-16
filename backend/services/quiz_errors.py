"""Moved to services/quiz/errors.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_errors.<name>")`
both land on the real one. New code imports services.quiz.errors."""
import sys

from services.quiz import errors

sys.modules[__name__] = errors
