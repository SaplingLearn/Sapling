"""The tutor package's one ``fastapi`` import (#118).

The tutor's HTTP answers are already ``HTTPException`` all the way down: the
session store it builds on (services/tutor_sessions.py) raises the 404/409s,
and the turn's guardrail mapping (``turns._agent_turn_or_http_error``) passes
those through unchanged while mapping the agent's own failures to 413/502.
The handler bodies moved here verbatim, so they keep raising the same class;
this module is the single place the package reaches into fastapi for it.
"""
from fastapi import HTTPException

__all__ = ["HTTPException"]
