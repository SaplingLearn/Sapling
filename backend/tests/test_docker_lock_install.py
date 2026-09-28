"""The backend image installs the dependency set CI tests (#694).

CI installs requirements.lock with --require-hashes. The Dockerfile used to
install the bare requirements.txt, so `genai-prices` 0.1.x floated into the
deployed image while CI pinned 0.0.66, and every `llm_usage` row recorded 0
tokens for two months (#689). The image now installs requirements.txt under
constraints derived from the lock (scripts/lock_constraints.py). These tests
keep that wiring from silently regressing. They read files only: no network,
no docker.
"""

import os
import re
import shlex

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from scripts.lock_constraints import (
    LockedPin,
    canonical,
    constraints_text,
    find_drift,
    parse_lock,
)

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_OCR_STACK = {"torch", "docling", "transformers"}
_CONSTRAINTS = "/tmp/lock-constraints.txt"


def _read(name: str) -> str:
    with open(os.path.join(_BACKEND, name), encoding="utf-8") as fh:
        return fh.read()


def _run_commands() -> list[list[str]]:
    """Every shell command in the Dockerfile's RUN instructions, tokenised."""
    text = re.sub(r"\\\n", " ", _read("Dockerfile"))
    commands = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("RUN "):
            continue
        for part in re.split(r"&&|;", line[len("RUN ") :]):
            tokens = shlex.split(part)
            if tokens:
                commands.append(tokens)
    return commands


def _pip_installs() -> list[list[str]]:
    return [c for c in _run_commands() if c[:2] == ["pip", "install"]]


def _requirements() -> list[Requirement]:
    reqs = []
    for raw in _read("requirements.txt").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            reqs.append(Requirement(line))
    return reqs


def _lock_pins() -> dict[str, LockedPin]:
    return {canonical(p.name): p for p in parse_lock(_read("requirements.lock"))}


# --- Dockerfile wiring -------------------------------------------------------


def test_dockerfile_installs_requirements_under_lock_constraints():
    installs = [c for c in _pip_installs() if "requirements.txt" in c]
    assert installs, "the Dockerfile no longer installs requirements.txt"
    for cmd in installs:
        assert "-c" in cmd and cmd[cmd.index("-c") + 1] == _CONSTRAINTS, (
            f"requirements.txt must be installed under the lock constraints (#694): {cmd}"
        )


def test_dockerfile_derives_constraints_from_the_lock_before_installing():
    commands = _run_commands()
    derive = next(
        (
            i
            for i, c in enumerate(commands)
            if c[:4]
            == ["python", "scripts/lock_constraints.py", "constraints", "requirements.lock"]
            and c[-2:] == [">", _CONSTRAINTS]
        ),
        None,
    )
    assert derive is not None, "the Dockerfile must derive the constraints from requirements.lock"
    first_install = next(i for i, c in enumerate(commands) if c[:2] == ["pip", "install"])
    assert derive < first_install


def test_dockerfile_copies_the_lock_and_script_into_the_install_layer():
    dockerfile = _read("Dockerfile")
    copy_all = dockerfile.index("COPY . .")
    early = dockerfile[:copy_all]
    assert re.search(r"^COPY [^\n]*requirements\.lock", early, re.MULTILINE)
    assert re.search(r"^COPY [^\n]*scripts/lock_constraints\.py", early, re.MULTILINE)


def test_dockerfile_verifies_the_installed_set_after_the_last_install():
    commands = _run_commands()
    last_install = max(i for i, c in enumerate(commands) if c[:2] == ["pip", "install"])
    verify = [
        i
        for i, c in enumerate(commands)
        if c == ["python", "scripts/lock_constraints.py", "verify", "requirements.lock"]
    ]
    assert verify and verify[-1] > last_install, (
        "lock_constraints.py verify must run after every pip install in the Dockerfile"
    )


def test_only_the_cpu_torch_install_runs_outside_the_constraints():
    """Any new `pip install` line must use the lock constraints too.

    The torch step is the one exception: it installs from the CPU wheel index,
    which does not carry every locked version. The constrained install that
    follows re-resolves torch's dependencies against the lock, and `verify`
    catches anything left over.
    """
    unconstrained = [c for c in _pip_installs() if "-c" not in c]
    assert len(unconstrained) == 1, unconstrained
    (torch_step,) = unconstrained
    assert "https://download.pytorch.org/whl/cpu" in torch_step
    assert "torch>=2.5,<3" in torch_step and "-r" not in torch_step


# --- requirements.txt vs the lock ---------------------------------------------
# (tests/test_requirements_lock.py already checks the lock pins every non-OCR
# requirement.)


def test_ocr_stack_is_left_out_of_the_constraints():
    """The OCR stack must stay unconstrained, so it keeps its CPU-index install."""
    pins = _lock_pins()
    assert not _OCR_STACK & set(pins)


def test_lock_pins_satisfy_requirements_txt():
    """A lock pin outside its requirements.txt range fails the image build.

    Catch that here, in the hermetic suite, instead of at deploy time.
    """
    pins = _lock_pins()
    conflicts = []
    for req in _requirements():
        pin = pins.get(canonical(req.name))
        if pin is None:
            continue
        if not req.specifier.contains(Version(pin.version), prereleases=True):
            conflicts.append(f"{req}: lock pins {pin.version}")
    assert conflicts == [], conflicts


# --- scripts/lock_constraints.py ----------------------------------------------


def test_constraints_cover_every_lock_pin_without_hashes():
    lock = _read("requirements.lock")
    text = constraints_text(parse_lock(lock))
    lines = text.splitlines()
    assert "--hash" not in text and "\\" not in text and "[" not in text
    top_level = [
        ln for ln in lock.splitlines() if ln and not ln[0].isspace() and not ln.startswith("#")
    ]
    assert len(lines) == len(top_level)
    for line in lines:
        Requirement(line)  # each line is a valid pip requirement


def test_parse_lock_keeps_markers_and_drops_extras():
    lock = (
        "# header\n"
        "\n"
        "anyio==4.14.0 \\\n"
        "    --hash=sha256:aaa \\\n"
        "    --hash=sha256:bbb\n"
        "    # via\n"
        "    #   httpx\n"
        "colorama==0.4.6 ; sys_platform == 'win32' \\\n"
        "    --hash=sha256:ccc\n"
        "uvicorn[standard]==0.49.0 \\\n"
        "    --hash=sha256:ddd\n"
    )
    assert constraints_text(parse_lock(lock)) == (
        "anyio==4.14.0\ncolorama==0.4.6 ; sys_platform == 'win32'\nuvicorn==0.49.0\n"
    )


def test_parse_lock_rejects_unknown_lines():
    with pytest.raises(ValueError):
        parse_lock("fastapi>=0.1 \\\n    --hash=sha256:aaa\n")
    with pytest.raises(ValueError):
        parse_lock("# only comments\n")


def _drift(pins, installed, applies=lambda m: True):
    return find_drift(
        pins,
        version_of=installed.get,
        marker_applies=applies,
        versions_equal=lambda a, b: Version(a) == Version(b),
    )


def test_verify_flags_a_package_that_drifted_from_its_pin():
    """The #689 shape: the lock pins genai-prices 0.0.66, the image has 0.1.9."""
    pins = [LockedPin("genai-prices", "0.0.66"), LockedPin("fastapi", "0.138.0")]
    problems, checked = _drift(pins, {"genai-prices": "0.1.9", "fastapi": "0.138.0"})
    assert problems == ["genai-prices: installed 0.1.9, lock pins 0.0.66"]
    assert checked == 2


def test_verify_ignores_missing_packages_and_non_matching_markers():
    pins = [
        LockedPin("colorama", "0.4.6", "sys_platform == 'win32'"),
        LockedPin("not-needed", "1.0"),
        LockedPin("httpx", "0.28.1"),
    ]
    problems, checked = _drift(
        pins,
        {"colorama": "0.4.0", "httpx": "0.28.1"},
        applies=lambda marker: marker != "sys_platform == 'win32'",
    )
    assert problems == [] and checked == 1
