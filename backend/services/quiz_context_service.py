"""Moved to services/quiz/context.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_context_service.<name>")`
both land on the real one. New code imports services.quiz.context."""
import sys

from services.quiz import context

sys.modules[__name__] = context
