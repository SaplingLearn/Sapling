"""
backend/routes/_docs.py

Route-side helper (not a router) for the #118 thin route wrappers whose bodies
moved into a ``services/<domain>/`` package.
"""
from __future__ import annotations


def same_doc(source):
    """Give a wrapper its body's docstring BEFORE `router` registers it.

    FastAPI publishes a handler's docstring as the OpenAPI description, so the
    wrapper must carry it for /openapi.json to stay byte-identical across the
    #118 split. Only the docstring: `functools.wraps` would also set
    `__wrapped__`, and FastAPI would then read the body's parameter
    annotations (starlette types) instead of this wrapper's.
    """
    def apply(fn):
        fn.__doc__ = source.__doc__
        return fn
    return apply
