"""Moved to ``services/flashcards/importing.py`` (#118).

This old path stays importable for open branches: it aliases the module
itself, so ``from services.flashcard_import_service import x`` and
``patch("services.flashcard_import_service.x")`` both reach the one real
module. New code imports ``services.flashcards`` (or ``.importing``).
"""

import sys

from services.flashcards import importing as _importing

sys.modules[__name__] = _importing
