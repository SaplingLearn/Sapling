"""Hermetic coverage for services/durable.py (ADR 0011 / #154).

Runs WITHOUT the `dbos` package installed (it lives only in
requirements-durable.txt, never requirements.txt/requirements.lock — see
that file's header). Each test reloads `services.durable` under a
monkeypatched env + a fake `sys.modules['dbos']`, so it can flip through
every precondition combination in one process without the real package.

The `durable_module` fixture guarantees the shared `services.durable`
module object is back in its pristine, flag-off, passthrough state before
the next test runs, regardless of what a given test set — other modules
(agents.document, and anything importing it) hold their OWN references to
whatever `workflow`/`step` looked like at THEIR import time, so this reload
only affects code that reads `services.durable.<name>` fresh; but the
module's global state must not leak across tests in this file, or into any
other test file that imports `services.durable` directly.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
import types
from functools import wraps

import pytest

import services.durable as durable

_ENV_KEYS = ("DBOS_ENABLED", "DBOS_DATABASE_URL")


@pytest.fixture
def durable_module():
    """Yield the live `services.durable` module; restore env, sys.modules,
    and the module's own state to pristine passthrough in a finally block
    so a test that blows up mid-way still can't leak into the rest of the
    suite (which imports agents.document -> services.durable at collection
    time)."""
    saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
    had_dbos = "dbos" in sys.modules
    saved_dbos = sys.modules.get("dbos")
    try:
        yield durable
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if had_dbos:
            sys.modules["dbos"] = saved_dbos
        else:
            sys.modules.pop("dbos", None)
        importlib.reload(durable)


def _make_stub_dbos_class(*, launch_raises: bool = False):
    """A fresh fake `DBOS` class per call (class-level counters, so reusing
    one across tests would leak call counts between them)."""

    class _StubDBOS:
        construct_count = 0
        launch_count = 0
        destroy_count = 0
        constructed_with: dict | None = None
        workflow_calls: list = []
        step_calls: list = []

        def __init__(self, *, config):
            type(self).construct_count += 1
            type(self).constructed_with = dict(config)

        @classmethod
        def workflow(cls, *args, **kwargs):
            def decorator(fn):
                cls.workflow_calls.append(fn)

                @wraps(fn)
                async def wrapper(*a, **k):
                    return await fn(*a, **k)

                return wrapper

            return decorator

        @classmethod
        def step(cls, *args, **kwargs):
            def decorator(fn):
                cls.step_calls.append(fn)

                @wraps(fn)
                async def wrapper(*a, **k):
                    return await fn(*a, **k)

                return wrapper

            return decorator

        @classmethod
        def launch(cls):
            cls.launch_count += 1
            if launch_raises:
                raise RuntimeError("stub launch failure")

        @classmethod
        def destroy(cls):
            cls.destroy_count += 1

    return _StubDBOS


def _install_stub_dbos(*, launch_raises: bool = False):
    """Install a fake `dbos` module into sys.modules and return
    (fake_module, stub_DBOS_class)."""
    stub_cls = _make_stub_dbos_class(launch_raises=launch_raises)
    fake_module = types.ModuleType("dbos")
    fake_module.DBOS = stub_cls
    fake_module.DBOSConfig = dict  # only used as a type annotation at runtime
    sys.modules["dbos"] = fake_module
    return fake_module, stub_cls


def _install_broken_dbos():
    """Force `from dbos import DBOS` to raise ImportError on reload, the
    same failure mode as `dbos` genuinely not being installed."""
    sys.modules["dbos"] = None


# ── Default (flag off): passthrough ─────────────────────────────────────────

def test_default_flag_off_is_durable_false(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    os.environ.pop("DBOS_DATABASE_URL", None)
    sys.modules.pop("dbos", None)
    d = importlib.reload(durable_module)
    assert d.is_durable() is False


def test_passthrough_workflow_preserves_return_value_and_args(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)

    calls = []

    @d.workflow
    async def wf(a, b, *, c=1):
        calls.append((a, b, c))
        return a + b + c

    result = asyncio.run(wf(1, 2, c=3))
    assert result == 6
    assert calls == [(1, 2, 3)]


def test_passthrough_step_preserves_return_value_and_args(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)

    calls = []

    @d.step
    async def st(a, b, *, c=1):
        calls.append((a, b, c))
        return a + b + c

    result = asyncio.run(st(4, 5, c=6))
    assert result == 15
    assert calls == [(4, 5, 6)]


def test_passthrough_workflow_propagates_exceptions(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)

    @d.workflow
    async def wf():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(wf())


def test_passthrough_step_propagates_exceptions(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)

    @d.step
    async def st():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        asyncio.run(st())


def test_init_dbos_noop_when_flag_off(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)
    assert d.init_dbos() is False


def test_shutdown_dbos_noop_when_flag_off(durable_module):
    os.environ.pop("DBOS_ENABLED", None)
    d = importlib.reload(durable_module)
    d.shutdown_dbos()  # must not raise


# ── DBOS_ENABLED=true but `dbos` fails to import ────────────────────────────

def test_enabled_but_dbos_import_fails_warns_then_init_dbos_raises(durable_module, caplog):
    os.environ["DBOS_ENABLED"] = "true"
    os.environ["DBOS_DATABASE_URL"] = "postgresql://x/y"
    _install_broken_dbos()
    with caplog.at_level(logging.WARNING, logger="services.durable"):
        d = importlib.reload(durable_module)
    # Import-time behavior is unchanged: warn + degrade decorators to
    # passthrough (an import-time raise would take the whole app down
    # before validate_config() runs — see the module docstring).
    assert d.is_durable() is False
    assert any("could not be imported" in r.message for r in caplog.records)

    # init_dbos() behavior changed (#154 review round, Finding B): this
    # precondition failure now fails loud at startup instead of returning
    # False and silently serving requests with zero durability.
    with pytest.raises(RuntimeError, match="could not be imported"):
        d.init_dbos()


# ── DBOS_ENABLED=true + working stub + DBOS_DATABASE_URL set: real mode ────

def test_enabled_with_working_stub_and_url_activates_durable(durable_module):
    os.environ["DBOS_ENABLED"] = "true"
    os.environ["DBOS_DATABASE_URL"] = "postgresql://u:p@localhost:5432/dbosdb"
    _fake_module, stub_cls = _install_stub_dbos()
    d = importlib.reload(durable_module)
    assert d.is_durable() is True

    @d.workflow
    async def wf(x):
        return x

    @d.step
    async def st(x):
        return x

    # Decorators delegated to the stub instead of falling through to the
    # identity passthrough.
    assert len(stub_cls.workflow_calls) == 1
    assert len(stub_cls.step_calls) == 1
    assert asyncio.run(wf("hi")) == "hi"
    assert asyncio.run(st("hi")) == "hi"

    assert d.init_dbos() is True
    assert stub_cls.construct_count == 1
    assert stub_cls.launch_count == 1
    assert stub_cls.constructed_with == {
        "name": "sapling",
        "system_database_url": "postgresql://u:p@localhost:5432/dbosdb",
    }

    d.shutdown_dbos()
    assert stub_cls.destroy_count == 1


# ── DBOS_ENABLED=true + working stub but NO DBOS_DATABASE_URL ───────────────

def test_enabled_without_database_url_warns_then_init_dbos_raises(durable_module, caplog):
    os.environ["DBOS_ENABLED"] = "true"
    os.environ.pop("DBOS_DATABASE_URL", None)
    _install_stub_dbos()
    with caplog.at_level(logging.WARNING, logger="services.durable"):
        d = importlib.reload(durable_module)
    # Import-time behavior is unchanged: warn + degrade to passthrough.
    assert d.is_durable() is False
    assert any("DBOS_DATABASE_URL" in r.message for r in caplog.records)

    # init_dbos() behavior changed (#154 review round, Finding B): raises
    # instead of returning False, naming the missing precondition.
    with pytest.raises(RuntimeError, match="DBOS_DATABASE_URL"):
        d.init_dbos()


# ── DBOS_ENABLED=true + stub whose launch() raises: fail-loud contract ─────

def test_init_dbos_raises_when_launch_fails(durable_module):
    os.environ["DBOS_ENABLED"] = "true"
    os.environ["DBOS_DATABASE_URL"] = "postgresql://u:p@localhost:5432/dbosdb"
    _fake_module, stub_cls = _install_stub_dbos(launch_raises=True)
    d = importlib.reload(durable_module)
    assert d.is_durable() is True

    with pytest.raises(RuntimeError, match="stub launch failure"):
        d.init_dbos()
    assert stub_cls.launch_count == 1
