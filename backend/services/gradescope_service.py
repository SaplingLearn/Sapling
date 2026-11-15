"""
backend/services/gradescope_service.py — re-export shim (#118).

The Gradescope client moved to ``services/gradescope/client.py``. This path
stays so existing imports (``from services import gradescope_service``) and
patch targets (``patch.object(gradescope_service, ...)``) keep working: the
old name is bound to the SAME module object, so a patch through either name
reaches the code that runs. New code imports ``services.gradescope.client``.
"""
import sys

from services.gradescope import client as _client

sys.modules[__name__] = _client
