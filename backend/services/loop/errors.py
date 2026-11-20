"""The loop package's one ``fastapi`` import (#118).

The loop's HTTP answers are ``HTTPException`` all the way down (the session
store, the guards and the tutor's guardrail mapping it builds on raise them
too), and its handler bodies moved here verbatim, so they keep raising the
same class; this module is the single place the package reaches into fastapi
for it (as ``services/tutor/errors.py`` is for the tutor).
"""
from fastapi import HTTPException

__all__ = ["HTTPException"]
