"""Moved to services/quiz/signals.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_signals.<name>")`
both land on the real one. New code imports services.quiz.signals."""
import sys

from services.quiz import signals

sys.modules[__name__] = signals
