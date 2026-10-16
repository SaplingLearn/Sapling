"""#620 resolver: precedence, fail-closed, caching, rollout stability."""
from unittest.mock import MagicMock, patch

import pytest

from services import feature_flags as ff

KEY = "hide_quiz"  # registry: ("off", "on"), client_visible


def _paged(rows):
    """select_with_count as `page_all` calls it: one page, then the end."""
    return lambda *a, **k: ((rows or []) if not k.get("offset") else [], len(rows or []))


def _tables(flags=None, targets=None, roles=None, fail=False):
    """table() factory: feature_flags / feature_flag_targets / user_roles."""
    def factory(name):
        m = MagicMock()
        if fail:
            m.select.side_effect = RuntimeError("db down")
            m.select_with_count.side_effect = RuntimeError("db down")
        elif name == "feature_flags":
            m.select_with_count.side_effect = _paged(flags)
        elif name == "feature_flag_targets":
            m.select_with_count.side_effect = _paged(targets)
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
    monkeypatch.setenv("SAPLING_FLAG_HIDE_QUIZ", "on")
    with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
        r = ff.explain(KEY, "u1")
    assert (r.variant, r.step) == ("on", "env_override")
    monkeypatch.setenv("SAPLING_FLAG_HIDE_QUIZ", "banana")
    with patch("services.feature_flags.table", side_effect=_tables(flags=[_row("off")])):
        assert ff.flag_variant(KEY, "u1") == "off"


def test_resolved_client_flags_only_client_visible(monkeypatch):
    monkeypatch.setitem(ff.REGISTRY, "server_only",
                        ff.FlagDef("server_only", ("off", "on"), "test", False))
    with patch("services.feature_flags.table", side_effect=_tables()):
        out = ff.resolved_client_flags("u1")
    visible = {k for k, fd in ff.REGISTRY.items() if fd.client_visible}
    assert set(out) == visible
    assert "server_only" not in out


def test_require_flag_404_when_off():
    from fastapi import HTTPException
    dep = ff.require_flag(KEY)
    req = MagicMock()
    with patch("services.feature_flags.table", side_effect=_tables()), \
         patch("services.auth_guard.get_session_user_id", return_value="u1"):
        with pytest.raises(HTTPException) as e:
            dep(req)
    assert e.value.status_code == 404


# ── Final-review fixes (#620) ───────────────────────────────────────────────


def test_config_reads_page_in_a_stable_order():
    """Offset paging over an unordered select can skip or repeat rows at a
    page boundary; both tables page through `page_all` with a total order."""
    handles: dict[str, MagicMock] = {}
    base = _tables(flags=[_row("on")])

    def factory(name):
        handles[name] = base(name)
        return handles[name]

    with patch("services.feature_flags.table", side_effect=factory):
        ff.read_config()
    assert handles["feature_flags"].select_with_count.call_args.kwargs["order"] == "key"
    assert (handles["feature_flag_targets"].select_with_count.call_args.kwargs["order"]
            == "flag_key,target_type,target_id")


def test_config_read_pages_past_max_rows():
    rows = [{"flag_key": KEY, "target_type": "user", "target_id": f"u{i}", "variant": "on"}
            for i in range(1500)]

    def factory(name):
        m = MagicMock()
        if name == "feature_flag_targets":
            m.select_with_count.side_effect = lambda *a, **k: (
                rows[k["offset"]:k["offset"] + k["limit"]], len(rows))
        else:
            m.select_with_count.side_effect = _paged([])
        return m

    with patch("services.feature_flags.table", side_effect=factory):
        snap = ff.read_config()
    assert len(snap.targets[KEY]) == 1500


def test_snapshot_ttl_zero_always_reads_fresh(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_SNAPSHOT_TTL_S", "0")
    calls = {"n": 0}
    base = _tables(flags=[_row("on")])

    def counting(name):
        if name == "feature_flags":
            calls["n"] += 1
        return base(name)

    with patch("services.feature_flags.table", side_effect=counting):
        ff.flag_variant(KEY, "u1")
        ff.flag_variant(KEY, "u1")
    assert calls["n"] == 2


def test_snapshot_ttl_is_read_at_call_time(monkeypatch):
    """The E2E stack exports 0; a bad value falls back to the 30 s default."""
    monkeypatch.setenv("FEATURE_FLAGS_SNAPSHOT_TTL_S", "banana")
    assert ff.snapshot_ttl_s() == 30.0
    monkeypatch.setenv("FEATURE_FLAGS_SNAPSHOT_TTL_S", "-5")
    assert ff.snapshot_ttl_s() == 30.0
    monkeypatch.setenv("FEATURE_FLAGS_SNAPSHOT_TTL_S", "0")
    assert ff.snapshot_ttl_s() == 0.0
    monkeypatch.delenv("FEATURE_FLAGS_SNAPSHOT_TTL_S")
    assert ff.snapshot_ttl_s() == 30.0
    assert ff.roles_ttl_s() == 60.0


def test_roles_ttl_zero_always_reads_fresh(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_ROLES_TTL_S", "0")
    targets = [{"flag_key": KEY, "target_type": "role", "target_id": "r1", "variant": "on"}]
    calls = {"n": 0}
    base = _tables(flags=[_row()], targets=targets,
                   roles=[{"role_id": "r1", "roles": {"display_priority": 1}}])

    def counting(name):
        if name == "user_roles":
            calls["n"] += 1
        return base(name)

    with patch("services.feature_flags.table", side_effect=counting):
        assert ff.flag_variant(KEY, "u1") == "on"
        assert ff.flag_variant(KEY, "u1") == "on"
    assert calls["n"] == 2


def test_roles_are_cached_by_default():
    targets = [{"flag_key": KEY, "target_type": "role", "target_id": "r1", "variant": "on"}]
    calls = {"n": 0}
    base = _tables(flags=[_row()], targets=targets,
                   roles=[{"role_id": "r1", "roles": {"display_priority": 1}}])

    def counting(name):
        if name == "user_roles":
            calls["n"] += 1
        return base(name)

    with patch("services.feature_flags.table", side_effect=counting):
        ff.flag_variant(KEY, "u1")
        ff.flag_variant(KEY, "u1")
    assert calls["n"] == 1


def test_clear_during_an_in_flight_read_is_not_overwritten():
    """An admin write that clears the cache WHILE a read is in flight must
    win: the read began before the write, so its (stale) fill is dropped."""
    calls = {"n": 0}
    stale, fresh = _tables(flags=[_row("off")]), _tables(flags=[_row("on")])

    def factory(name):
        if name == "feature_flags":
            calls["n"] += 1
            if calls["n"] == 1:
                ff.clear_feature_flags_cache()  # the write lands mid-read
                return stale(name)
            return fresh(name)
        return (stale if calls["n"] == 1 else fresh)(name)

    with patch("services.feature_flags.table", side_effect=factory):
        assert ff.flag_variant(KEY, "u1") == "off"  # that read's own answer stands
        assert ff.flag_variant(KEY, "u1") == "on"   # ...but it was never cached
    assert calls["n"] == 2


def test_store_outage_warns_again_after_a_recovery(caplog):
    with caplog.at_level("WARNING", logger="sapling.feature_flags"):
        with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
            ff.flag_variant(KEY, "u1")
            ff.flag_variant(KEY, "u1")  # same outage: warned once
        with patch("services.feature_flags.table", side_effect=_tables(flags=[_row()])):
            ff.flag_variant(KEY, "u1")  # recovered
        ff.clear_feature_flags_cache()
        with patch("services.feature_flags.table", side_effect=_tables(fail=True)):
            ff.flag_variant(KEY, "u1")  # a later outage is news again
    unreadable = [r for r in caplog.records if "unreadable" in r.getMessage()]
    assert len(unreadable) == 2



def test_nav_flags_match_the_frontend_nav_list():
    """The hide_* flags and frontend/src/lib/navFeatures.ts name the same set:
    a flag the nav never reads is a dead /admin switch, and a nav flag the
    registry lacks resolves to "off" forever (unregistered → fail-closed)."""
    import re
    from pathlib import Path

    nav = Path(__file__).resolve().parents[2] / "frontend/src/lib/navFeatures.ts"
    frontend = set(re.findall(r'flag: "(hide_[a-z_]+)"', nav.read_text()))
    backend = {k for k in ff.REGISTRY if k.startswith("hide_")}
    assert frontend == backend == {f"hide_{slug}" for slug, _ in ff.NAV_FEATURES}
    assert all(ff.REGISTRY[k].client_visible and ff.REGISTRY[k].variants == ("off", "on")
               for k in backend)
