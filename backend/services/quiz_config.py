"""Moved to services/quiz/config.py (#118). Kept for open branches: this path is
an ALIAS of that module, so imports and `patch("services.quiz_config.<name>")`
both land on the real one. New code imports services.quiz.config."""
import sys

from services.quiz import config

sys.modules[__name__] = config
