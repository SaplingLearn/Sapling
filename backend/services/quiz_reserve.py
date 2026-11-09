"""Moved to services/quiz/reserve.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_reserve.<name>")`
both land on the real one. New code imports services.quiz.reserve."""
import sys

from services.quiz import reserve

sys.modules[__name__] = reserve
