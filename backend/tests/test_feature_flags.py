"""#620 resolver: precedence, fail-closed, caching, rollout stability."""
from unittest.mock import MagicMock, patch

import pytest

from services import feature_flags as ff

KEY = "learning_loop"  # registry: ("off", "on"), client_visible


def _tables(flags=None, targets=None, roles=None, fail=False):
    """table() factory: feature_flags / feature_flag_targets / user_roles."""
    def factory(name):
        m = MagicMock()
        if fail:
            m.select.side_effect = RuntimeError("db down")
        elif name == "feature_flags":
            m.select.side_effect = lambda *a, **k: (flags or []) if not k.get("offset") else []
        elif name == "feature_flag_targets":
            m.select.side_effect = lambda *a, **k: (targets or []) if not k.get("offset") else []
        elif name == "user_roles":
            m.select.return_value = roles or []
        else:
            m.select.return_value = []
        return m
    return factory


def _row(default="off", pct=0, rv=None):
    return {"key": KEY, "default_variant": default, "rollout_percent": pct,
            "rollout_variant": rv, "updated_at": None, "updated_by": None}


def test_registry_variants_start_with_off():
    for fd in ff.REGISTRY.values():
        assert fd.variants[0] == "off"


def test_no_row_is_off_default():
    with patch("services.feature_flags.table", side_effect=_tables()):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "default")


def test_default_row():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("on")])):
        assert ff.flag_variant(KEY, "u1") == "on"
        assert ff.flag_on(KEY, "u1") is True


def test_user_rule_beats_role_rollout_default():
    targets = [
        {"flag_key": KEY, "target_type": "user", "target_id": "u1", "variant": "off"},
        {"flag_key": KEY, "target_type": "role", "target_id": "r1", "variant": "on"},
    ]
    roles = [{"role_id": "r1", "roles": {"display_priority": 100}}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row("on", 100, "on")], targets=targets, roles=roles)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "user")


def test_role_priority_then_lowest_id():
    targets = [
        {"flag_key": KEY, "target_type": "role", "target_id": "r-low", "variant": "off"},
        {"flag_key": KEY, "target_type": "role", "target_id": "r-high", "variant": "on"},
    ]
    roles = [{"role_id": "r-low", "roles": {"display_priority": 10}},
             {"role_id": "r-high", "roles": {"display_priority": 80}}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row()], targets=targets, roles=roles)):
        assert ff.explain(KEY, "u1").variant == "on"
    ff.clear_feature_flags_cache()
    ff.clear_user_roles_cache()
    tie = [{"role_id": "b", "roles": {"display_priority": 50}},
           {"role_id": "a", "roles": {"display_priority": 50}}]
    t2 = [{"flag_key": KEY, "target_type": "role", "target_id": "a", "variant": "on"},
          {"flag_key": KEY, "target_type": "role", "target_id": "b", "variant": "off"}]
    with patch("services.feature_flags.table",
               side_effect=_tables(flags=[_row()], targets=t2, roles=tie)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step, r.detail) == ("on", "role", "a")


def test_rollout_membership_only_grows():
    users = [f"user_{i}" for i in range(400)]
    at10 = {u for u in users if ff.rollout_bucket(KEY, u) < 10}
    at20 = {u for u in users if ff.rollout_bucket(KEY, u) < 20}
    assert at10 and at10 <= at20 and len(at20) > len(at10)
    assert ff.rollout_bucket(KEY, "user_7") == ff.rollout_bucket(KEY, "user_7")


def test_rollout_applies_to_bucket():
    inside = next(u for u in (f"u{i}" for i in range(1000)) if ff.rollout_bucket(KEY, u) < 30)
    outside = next(u for u in (f"u{i}" for i in range(1000)) if ff.rollout_bucket(KEY, u) >= 30)
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off", 30, "on")])):
        assert ff.explain(KEY, inside).step == "rollout"
        assert ff.flag_variant(KEY, inside) == "on"
        assert ff.flag_variant(KEY, outside) == "off"


def test_anonymous_skips_user_role_rollout():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off", 100, "on")])):
        r = ff.explain(KEY, None)
    assert (r.variant, r.step) == ("off", "default")


def test_invalid_stored_variant_is_off():
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("banana")])):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "fail_closed")


def test_unregistered_key_is_off():
    assert ff.flag_variant("no_such_flag", "u1") == "off"
    assert ff.flag_on("no_such_flag", "u1") is False


def test_store_failure_fails_closed_and_is_not_cached():
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("off", "fail_closed")
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("on")])):
        assert ff.flag_variant(KEY, "u1") == "on"  # retried, not a cached failure


def test_snapshot_is_cached_until_cleared():
    calls = {"n": 0}
    base = _tables(flags=[_row("on")])

    def counting(name):
        if name == "feature_flags":
            calls["n"] += 1
        return base(name)

    with patch("services.feature_flags.table", side_effect=counting):
        ff.flag_variant(KEY, "u1")
        ff.flag_variant(KEY, "u2")
        assert calls["n"] == 1
        ff.clear_feature_flags_cache()
        ff.flag_variant(KEY, "u1")
        assert calls["n"] == 2


def test_env_override(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "on")
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("on", "env_override")
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "banana")
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off")])):
        assert ff.flag_variant(KEY, "u1") == "off"


def test_resolved_client_flags_only_client_visible():
    with patch("services.feature_flags.table", side_effect=_tables()):
        out = ff.resolved_client_flags("u1")
    visible = {k for k, fd in ff.REGISTRY.items() if fd.client_visible}
    assert set(out) == visible
    assert "decision_router" not in out


def test_require_flag_404_when_off():
    from fastapi import HTTPException
    dep = ff.require_flag(KEY)
    req = MagicMock()
    with patch("services.feature_flags.table", side_effect=_tables()), \
         patch("services.auth_guard.get_session_user_id", return_value="u1"):
        with pytest.raises(HTTPException) as e:
            dep(req)
    assert e.value.status_code == 404
