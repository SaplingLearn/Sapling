"""Phase 4 (#118) code-size ratchet: complexity and route-file length can only go down.

The real checks measure the backend tree against ``code_size_baseline.json``
(logic in ``scripts/code_size_ratchet.py``). The rest pins the ratchet's own
rules on synthetic numbers, so a refactor of the script cannot quietly turn it
into a no-op.

When a real check fails:
  * a NEW offender: split the function / move the route's logic into a service
    module (docs/design/domain-modules.md). Do not add a baseline entry.
  * a baselined entry GREW: shrink it back under its ceiling. If that is
    genuinely impossible in this change, raising the number in the JSON is a
    hand edit the reviewer has to accept.
  * it went DOWN: nothing fails (the slack tests only warn, so two PRs that
    each shrink a file cannot turn main red between them), but lower the
    baseline so the gain sticks: ``python scripts/code_size_ratchet.py
    --shrink`` (from backend/).
"""

from __future__ import annotations

import pathlib
import tomllib
import warnings

import pytest

from scripts import code_size_ratchet as ratchet

ROOT = ratchet.BACKEND


class BaselineSlackWarning(UserWarning):
    """A baselined entry is now lower than its ceiling: run --shrink."""


_HOW_TO_SHRINK = (
    "Lock in the improvement: run `python scripts/code_size_ratchet.py --shrink` from backend/ "
    "and commit code_size_baseline.json."
)


@pytest.fixture(scope="module")
def baseline():
    return ratchet.load_baseline(ROOT)


@pytest.fixture(scope="module")
def complexity():
    return ratchet.measure_complexity(ROOT)


def _fail_message(problems: list[str], what: str) -> str:
    return (
        f"{what} ratchet (#118) — fix these, do not add baseline entries:\n  "
        + "\n  ".join(problems)
        + "\nSee docs/design/domain-modules.md for where the code should move."
    )


def test_no_function_exceeds_its_complexity_ceiling(baseline, complexity):
    problems = ratchet.compare(baseline["complexity"], complexity, ratchet.max_complexity(ROOT))
    assert not problems, _fail_message(problems, "C901 complexity")


def test_no_route_file_exceeds_its_line_ceiling(baseline):
    current = ratchet.measure_route_file_lines(ROOT)
    problems = ratchet.compare(baseline["route_file_lines"], current, ratchet.ROUTE_FILE_MAX_LINES)
    assert not problems, _fail_message(problems, "Route-file length")


def _warn_slack(slack: list[str], what: str) -> None:
    """Slack only warns. Failing on it would let two independently-green PRs
    that each shrink a file leave main red (each lowers the JSON to a number
    the other's change makes stale); only growth and new offenders fail."""
    if slack:
        warnings.warn(
            "\n  ".join([f"{what} baseline has slack:", *slack, _HOW_TO_SHRINK]),
            BaselineSlackWarning,
            stacklevel=2,
        )


def test_complexity_baseline_slack_is_reported(baseline, complexity):
    """A function that got simpler should have its ceiling lowered, or the
    headroom becomes room for the next regression."""
    _warn_slack(ratchet.shrinkable(baseline["complexity"], complexity), "complexity")


def test_route_file_baseline_slack_is_reported(baseline):
    current = ratchet.measure_route_file_lines(ROOT)
    _warn_slack(ratchet.shrinkable(baseline["route_file_lines"], current), "route-file")


def test_slack_warns_instead_of_failing():
    with pytest.warns(BaselineSlackWarning, match="lower it"):
        _warn_slack(ratchet.shrinkable({"a": 30}, {"a": 27}), "complexity")


def test_ruff_c901_file_ignores_match_the_baseline(baseline):
    """ruff.toml's per-file C901 exemptions exist only for files that still
    hold a baselined function — otherwise a cleaned-up file stays exempt and
    `ruff check .` stops catching new offenders in it."""
    baselined_files = {key.split("::", 1)[0] for key in baseline["complexity"]}
    ignored = ratchet.c901_ignored_files(ROOT)
    assert ignored == baselined_files, (
        f"ruff.toml C901 per-file-ignores {sorted(ignored)} != files in "
        f"code_size_baseline.json {sorted(baselined_files)}; add or remove the ruff.toml entry"
    )


def test_ruff_toml_has_no_other_way_to_hide_a_function():
    """Plain `ruff check .` honours excludes, extend-per-file-ignores and ignore
    lists; the ratchet's measurement does not (it runs --isolated). Keep
    ruff.toml free of them so the two cannot disagree."""
    assert ratchet.c901_config_bypasses(ROOT) == []


def test_threshold_is_the_phase_4_target():
    assert ratchet.max_complexity(ROOT) == 25
    assert ratchet.ROUTE_FILE_MAX_LINES == 600


def test_ruff_exempts_exactly_the_exempt_dirs_from_c901():
    config = tomllib.loads((ROOT / "ruff.toml").read_text())
    ignores = config["lint"]["per-file-ignores"]
    for d in ratchet.COMPLEXITY_EXEMPT_DIRS:
        assert "C901" in ignores.get(f"{d}**", []), f'ruff.toml needs "{d}**" = ["C901"]'


# --- the ratchet's own rules, on synthetic numbers -------------------------


def test_compare_flags_new_offenders_and_growth_only():
    baseline = {"a": 30, "b": 30}
    current = {"a": 30, "b": 31, "c": 26}
    assert ratchet.compare(baseline, current, 25) == [
        "b: 31 is over its baselined ceiling of 30",
        "c: 26 is over the limit of 25 (new)",
    ]


def test_compare_allows_shrinking_and_disappearing():
    assert ratchet.compare({"a": 30, "b": 30}, {"a": 27}, 25) == []


def test_shrink_lowers_and_drops_but_never_adds_or_raises():
    baseline = {"lower": 30, "gone": 30, "grew": 30}
    current = {"lower": 27, "grew": 35, "new": 40}
    assert ratchet.shrink(baseline, current) == {"lower": 27, "grew": 30}


def test_shrinkable_names_every_stale_entry():
    assert ratchet.shrinkable({"a": 30, "b": 30, "c": 30}, {"a": 30, "b": 28}) == [
        "b: now 28, baselined at 30 — lower it",
        "c: back under the limit — delete its entry",
    ]


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _branchy(name: str, branches: int, indent: str = "") -> str:
    body = "".join(
        f"{indent}    if x == {i}:\n{indent}        return {i}\n" for i in range(branches)
    )
    return f"{indent}def {name}(x):\n{body}{indent}    return -1\n"


def test_measure_complexity_sees_through_noqa_and_file_ignores(tmp_path):
    """The per-function ceiling must hold even where ruff.toml or an inline
    noqa silences C901 for `ruff check .`. Same-named methods are keyed by
    their class."""
    _write(
        tmp_path,
        "ruff.toml",
        (
            '[lint]\nselect = ["C901"]\n[lint.mccabe]\nmax-complexity = 3\n'
            '[lint.per-file-ignores]\n"pkg/mod.py" = ["C901"]\n'
        ),
    )
    _write(
        tmp_path,
        "pkg/mod.py",
        (
            _branchy("simple", 1)
            + "class A:\n"
            + _branchy("helper", 4, "    ")
            + "class B:\n"
            + _branchy("helper", 6, "    ")
            + _branchy("hushed", 5).replace("(x):", "(x):  # noqa: C901", 1)
        ),
    )
    assert ratchet.measure_complexity(tmp_path) == {
        "pkg/mod.py::A.helper": 5,
        "pkg/mod.py::B.helper": 7,
        "pkg/mod.py::hushed": 6,
    }


_LINT = '[lint]\nselect = ["C901"]\n'
_MCCABE = "[lint.mccabe]\nmax-complexity = 3\n"
# Full ruff.toml texts, each trying a different way to hide services/x.py.
_BYPASS_CONFIGS = {
    "extend-per-file-ignores": (
        _LINT + _MCCABE + '[lint.extend-per-file-ignores]\n"services/x.py" = ["C901"]\n'
    ),
    "extend-per-file-ignores prefix": (
        _LINT + _MCCABE + '[lint.extend-per-file-ignores]\n"services/*" = ["C90"]\n'
    ),
    "per-file-ignores prefix": _LINT + _MCCABE + '[lint.per-file-ignores]\n"services/*" = ["C"]\n',
    "extend-exclude": 'extend-exclude = ["services/x.py"]\n' + _LINT + _MCCABE,
    "exclude": 'exclude = ["services"]\n' + _LINT + _MCCABE,
    "lint.exclude": _LINT + 'exclude = ["services/**"]\n' + _MCCABE,
    "lint.ignore": _LINT + 'ignore = ["C"]\n' + _MCCABE,
    "include": 'include = ["main.py"]\n' + _LINT + _MCCABE,
}


@pytest.mark.parametrize("config", _BYPASS_CONFIGS.values(), ids=_BYPASS_CONFIGS.keys())
def test_ruff_toml_cannot_hide_a_function_from_the_ratchet(tmp_path, config):
    """Every ruff.toml knob that hides a file or C901 from `ruff check .` is
    ignored by the measurement (ruff --isolated), and flagged by
    c901_config_bypasses so plain `ruff check .` stays honest too."""
    _write(tmp_path, "ruff.toml", config)
    _write(tmp_path, "services/x.py", _branchy("hidden", 4))
    _write(tmp_path, "main.py", "x = 1\n")
    assert ratchet.measure_complexity(tmp_path) == {"services/x.py::hidden": 5}
    assert ratchet.c901_config_bypasses(tmp_path), "the bypass went unflagged"


def test_c901_config_bypasses_accepts_the_sanctioned_shape(tmp_path):
    _write(
        tmp_path,
        "ruff.toml",
        (
            '[lint]\nselect = ["F", "C901"]\nignore = ["E501"]\n'
            "[lint.mccabe]\nmax-complexity = 3\n"
            '[lint.per-file-ignores]\n"services/x.py" = ["C901"]\n"tests/**" = ["C901"]\n'
        ),
    )
    assert ratchet.c901_config_bypasses(tmp_path) == []


def test_same_named_methods_each_keep_their_own_ceiling(tmp_path):
    """Two `run` methods: the simpler one shrinking must not lend its ceiling
    to the other (score-ordered numbering used to swap them)."""
    _write(tmp_path, "ruff.toml", "[lint.mccabe]\nmax-complexity = 3\n")
    _write(
        tmp_path,
        "services/jobs.py",
        "class Big:\n" + _branchy("run", 3, "    ") + "class Small:\n" + _branchy("run", 6, "    "),
    )
    current = ratchet.measure_complexity(tmp_path)
    assert current == {"services/jobs.py::Big.run": 4, "services/jobs.py::Small.run": 7}
    baseline = {"services/jobs.py::Big.run": 9, "services/jobs.py::Small.run": 5}
    assert ratchet.compare(baseline, current, 3) == [
        "services/jobs.py::Small.run: 7 is over its baselined ceiling of 5"
    ]


def test_nested_and_redefined_functions_get_stable_keys(tmp_path):
    _write(tmp_path, "ruff.toml", "[lint.mccabe]\nmax-complexity = 3\n")
    nested = "def outer():\n" + _branchy("inner", 4, "    ") + "    return inner\n"
    _write(
        tmp_path,
        "services/x.py",
        nested + "async " + _branchy("dup", 6) + _branchy("dup", 4) + "class C:\n"
        "    @staticmethod\n" + _branchy("m", 5, "    "),
    )
    # McCabe folds a nested function's branches into its parent, so both score.
    assert ratchet.measure_complexity(tmp_path) == {
        "services/x.py::outer": 6,
        "services/x.py::outer.<locals>.inner": 5,
        "services/x.py::dup": 7,
        "services/x.py::dup#2": 5,
        "services/x.py::C.m": 6,
    }


def test_measure_route_file_lines_only_counts_routes_over_the_limit(tmp_path):
    _write(tmp_path, "routes/big.py", "x = 1\n" * 7)
    _write(tmp_path, "routes/sub/deep.py", "x = 1\n" * 9)
    _write(tmp_path, "routes/small.py", "x = 1\n" * 5)
    _write(tmp_path, "services/huge.py", "x = 1\n" * 50)
    assert ratchet.measure_route_file_lines(tmp_path, limit=5) == {
        "routes/big.py": 7,
        "routes/sub/deep.py": 9,
    }


def test_measure_complexity_skips_test_code(tmp_path):
    """tests/ is excluded from the ruff run itself (an unparseable test file
    would raise if it were linted then discarded); only the top-level tests/
    is exempt, not any directory that happens to be called tests."""
    _write(tmp_path, "ruff.toml", "[lint.mccabe]\nmax-complexity = 3\n")
    _write(tmp_path, "tests/test_x.py", _branchy("fake_table", 9))
    _write(tmp_path, "tests/broken.py", "def f(:\n")
    _write(tmp_path, "services/x.py", _branchy("real", 4))
    _write(tmp_path, "services/tests/y.py", _branchy("nested", 4))
    assert ratchet.measure_complexity(tmp_path) == {
        "services/tests/y.py::nested": 5,
        "services/x.py::real": 5,
    }


def _shrink_fixture(tmp_path, baseline_complexity: dict, branches: int) -> None:
    _write(tmp_path, "ruff.toml", "[lint.mccabe]\nmax-complexity = 3\n")
    _write(tmp_path, "services/x.py", _branchy("f", branches))
    (tmp_path / "routes").mkdir()
    ratchet.write_baseline({"complexity": baseline_complexity, "route_file_lines": {}}, tmp_path)


def test_shrink_lowers_the_baseline_and_exits_clean(tmp_path, capsys):
    _shrink_fixture(tmp_path, {"services/x.py::f": 9}, branches=4)
    assert ratchet.main(["--shrink", "--root", str(tmp_path)]) == 0
    assert ratchet.load_baseline(tmp_path)["complexity"] == {"services/x.py::f": 5}
    assert "FAIL" not in capsys.readouterr().out


def test_shrink_reports_what_it_cannot_fix(tmp_path, capsys):
    """--shrink never raises a ceiling, so growth survives it: it must say so
    and exit non-zero instead of implying the tree is clean."""
    _shrink_fixture(tmp_path, {"services/x.py::f": 4}, branches=6)
    assert ratchet.main(["--shrink", "--root", str(tmp_path)]) == 1
    assert ratchet.load_baseline(tmp_path)["complexity"] == {"services/x.py::f": 4}
    assert "services/x.py::f: 7 is over its baselined ceiling of 4" in capsys.readouterr().out


def test_measure_complexity_refuses_a_file_it_cannot_parse(tmp_path):
    """An unparseable file (say, left-over conflict markers) must not read as
    'its functions got simpler' — --shrink would then delete their ceilings."""
    _write(tmp_path, "ruff.toml", "[lint.mccabe]\nmax-complexity = 3\n")
    _write(tmp_path, "services/x.py", "<<<<<<< HEAD\ndef f(:\n")
    with pytest.raises(RuntimeError, match="cannot measure complexity: services/x.py"):
        ratchet.measure_complexity(tmp_path)
