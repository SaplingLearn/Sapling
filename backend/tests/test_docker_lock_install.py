"""The backend image installs the dependency set CI tests (#694).

CI installs requirements.lock with --require-hashes. The Dockerfile used to
install the bare requirements.txt, so `genai-prices` 0.1.x floated into the
deployed image while CI pinned 0.0.66, and every `llm_usage` row recorded 0
tokens for two months (#689). The image now installs requirements.txt under
constraints derived from the lock (scripts/lock_constraints.py). These tests
keep that wiring from silently regressing. They read files only: no network,
no docker.
"""

import json
import os
import re
import shlex

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from scripts.lock_constraints import (
    LockedPin,
    constraints_text,
    cuda_distributions,
    find_drift,
    installed_pin,
    parse_lock,
)
from tests.dependency_manifest import BACKEND, OCR_STACK, lock_pins, read, requirements

_CONSTRAINTS = "/tmp/lock-constraints.txt"
_SCRIPT = "scripts/lock_constraints.py"
_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"


# --- Dockerfile reader ---------------------------------------------------------


def _split_shell(line: str) -> list[str]:
    """Split a shell line on `&&`, `||`, `;` and `|`, but never inside quotes."""
    parts, buf, quote, i = [], [], None, 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < len(line):
                buf.append(line[i : i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            buf.append(ch)
        elif ch in "'\"":
            quote = ch
            buf.append(ch)
        elif line.startswith(("&&", "||"), i):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        elif ch in ";|":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:  # unbalanced quote: still see the words
        return command.split()


def _instructions(text: str) -> list[tuple[str, list[list[str]]]]:
    """Dockerfile instructions in order, as (INSTRUCTION, commands).

    A RUN yields one token list per shell command; any other instruction
    yields its arguments as a single token list.
    """
    text = re.sub(r"\\\n", " ", text)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        instr, _, rest = line.partition(" ")
        instr = instr.upper()
        rest = rest.strip()
        if instr == "RUN" and rest.startswith("["):  # exec form: one command, no shell
            out.append((instr, [json.loads(rest)]))
        elif instr == "RUN":
            out.append((instr, [_tokens(c) for c in _split_shell(rest)]))
        else:
            out.append((instr, [_tokens(rest)]))
    return out


def _run_commands(text: str) -> list[list[str]]:
    return [c for instr, cmds in _instructions(text) if instr == "RUN" for c in cmds]


_PYTHON = re.compile(r"(?:\S*/)?python(?:3(?:\.\d+)?)?")
_PIP = re.compile(r"(?:\S*/)?pip(?:3(?:\.\d+)?)?")


def _pip_install_args(tokens: list[str]) -> list[str] | None:
    """The arguments after `install` if `tokens` is any form of pip install."""
    t = tokens
    if len(t) >= 3 and _PYTHON.fullmatch(t[0]) and t[1:3] == ["-m", "pip"]:
        t = t[3:]
    elif t[:2] == ["uv", "pip"]:
        t = t[2:]
    elif t and _PIP.fullmatch(t[0]):
        t = t[1:]
    else:
        return None
    return t[1:] if t[:1] == ["install"] else None


def _installs(text: str) -> list[list[str]]:
    return [a for c in _run_commands(text) if (a := _pip_install_args(c)) is not None]


def _is_constrained(args: list[str]) -> bool:
    return any(a == "-c" and args[i + 1 : i + 2] == [_CONSTRAINTS] for i, a in enumerate(args))


def _is_cpu_torch_step(args: list[str]) -> bool:
    packages = [a for a in args if not a.startswith("-") and a != _TORCH_INDEX]
    return _TORCH_INDEX in args and packages == ["torch>=2.5,<3"]


def _unconstrained_installs(text: str) -> list[list[str]]:
    """Every pip install that runs outside the lock constraints, torch aside."""
    return [a for a in _installs(text) if not _is_constrained(a) and not _is_cpu_torch_step(a)]


def _positions(commands: list[list[str]], predicate) -> list[int]:
    return [i for i, c in enumerate(commands) if predicate(c)]


def _install_matching(predicate):
    return lambda c: (a := _pip_install_args(c)) is not None and predicate(a)


_DOCKERFILE = read("Dockerfile")


# --- Dockerfile wiring -------------------------------------------------------


def test_every_install_but_the_cpu_torch_step_is_under_the_lock_constraints():
    assert _unconstrained_installs(_DOCKERFILE) == []
    reqs = [a for a in _installs(_DOCKERFILE) if "requirements.txt" in a]
    assert reqs, "the Dockerfile no longer installs requirements.txt"
    assert all(_is_constrained(a) for a in reqs)


def test_torch_is_installed_once_from_the_cpu_index():
    assert len([a for a in _installs(_DOCKERFILE) if _is_cpu_torch_step(a)]) == 1


def test_constraints_come_from_the_lock_and_pin_the_installed_torch():
    """Without the torch pin, the constrained install may backtrack onto a PyPI torch (CUDA on Linux)."""
    cmds = _run_commands(_DOCKERFILE)
    derive = _positions(
        cmds,
        lambda c: c == ["python", _SCRIPT, "constraints", "requirements.lock", ">", _CONSTRAINTS],
    )
    pin = _positions(cmds, lambda c: c == ["python", _SCRIPT, "pin", "torch", ">>", _CONSTRAINTS])
    torch_step = _positions(cmds, _install_matching(_is_cpu_torch_step))
    constrained = _positions(cmds, _install_matching(_is_constrained))
    assert derive and pin and torch_step and constrained
    assert torch_step[0] < pin[0], "torch must be installed before its version is pinned"
    assert derive[0] < pin[0] < constrained[0], (
        "append the torch pin after the lock, before any constrained install"
    )


def test_verify_and_pip_check_run_after_the_last_install():
    cmds = _run_commands(_DOCKERFILE)
    last_install = max(_positions(cmds, lambda c: _pip_install_args(c) is not None))
    verify = _positions(cmds, lambda c: c == ["python", _SCRIPT, "verify", "requirements.lock"])
    pip_check = _positions(cmds, lambda c: c == ["pip", "check"])
    assert verify and verify[-1] > last_install
    assert pip_check and pip_check[-1] > last_install


def test_torch_layer_is_cached_ahead_of_the_lock():
    """A lock bump must not re-download torch, so its RUN comes before the lock COPY."""
    instrs = _instructions(_DOCKERFILE)

    def first(predicate):
        return next(i for i, (instr, cmds) in enumerate(instrs) if predicate(instr, cmds))

    is_torch = _install_matching(_is_cpu_torch_step)
    torch_run = first(lambda instr, cmds: instr == "RUN" and any(is_torch(c) for c in cmds))
    lock_copy = first(lambda instr, cmds: instr == "COPY" and "requirements.lock" in cmds[0])
    script_copy = first(lambda instr, cmds: instr == "COPY" and _SCRIPT in cmds[0])
    constrained_run = first(
        lambda instr, cmds: (
            instr == "RUN" and any(_install_matching(_is_constrained)(c) for c in cmds)
        )
    )
    assert torch_run < lock_copy < constrained_run
    assert script_copy < constrained_run


def test_image_python_matches_the_lock_and_ci():
    """The lock is compiled for one Python and applied as hard constraints; all three must agree."""
    image = re.search(r"^FROM python:(\d+\.\d+)", _DOCKERFILE, re.MULTILINE).group(1)
    lock = re.search(r"--python-version (\d+\.\d+)", read("requirements.lock")).group(1)
    ci = re.findall(r"python-version:\s*[\"']?(\d+\.\d+)", read("../.github/workflows/ci.yml"))
    assert ci and set(ci) == {lock}, (ci, lock)
    assert image == lock


def test_no_ci_lane_installs_the_unlocked_requirements():
    """Every workflow installs the hash-pinned lock, never the floating manifest."""
    workflows = os.path.join(BACKEND, "..", ".github", "workflows")
    offenders = []
    for name in sorted(os.listdir(workflows)):
        if not name.endswith((".yml", ".yaml")):
            continue
        for lineno, line in enumerate(
            read(os.path.join("..", ".github", "workflows", name)).splitlines(), 1
        ):
            code = line.split("#", 1)[0]
            if "pip install" not in code:
                continue
            if "requirements.txt" in code or (
                "requirements.lock" in code and "--require-hashes" not in code
            ):
                offenders.append(f"{name}:{lineno}: {code.strip()}")
    assert offenders == [], offenders


# --- the reader catches every install form ----------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "pip install -r requirements.txt",
        "pip3 install -r requirements.txt",
        "python -m pip install -r requirements.txt",
        "python3 -m pip install -r requirements.txt",
        "python3.13 -m pip install foo",
        "/usr/local/bin/python -m pip install foo",
        "uv pip install --system -r requirements.txt",
        "/usr/local/bin/pip install foo",
    ],
)
def test_reader_flags_every_unconstrained_pip_form(command):
    dockerfile = f"FROM python:3.13-slim\nRUN apt-get update && {command} && echo done\n"
    assert len(_unconstrained_installs(dockerfile)) == 1


def test_reader_accepts_constrained_and_exec_form_installs():
    dockerfile = (
        f"RUN python -m pip install -c {_CONSTRAINTS} -r requirements.txt\n"
        f'RUN ["uv", "pip", "install", "-c", "{_CONSTRAINTS}", "foo"]\n'
        'RUN ["pip", "install", "bar"]\n'
    )
    assert _unconstrained_installs(dockerfile) == [["bar"]]


def test_reader_does_not_split_inside_quotes():
    dockerfile = (
        f"RUN pip install -c {_CONSTRAINTS} \"foo ; sys_platform == 'linux'\" "
        "&& echo 'a && b; c | d' \\\n    && pip install bar\n"
    )
    assert _run_commands(dockerfile) == [
        ["pip", "install", "-c", _CONSTRAINTS, "foo ; sys_platform == 'linux'"],
        ["echo", "a && b; c | d"],
        ["pip", "install", "bar"],
    ]
    assert _unconstrained_installs(dockerfile) == [["bar"]]


def test_reader_survives_an_unbalanced_quote():
    assert _unconstrained_installs("RUN pip install \"foo\nRUN echo 'x\n") == [['"foo']]


# --- requirements.txt vs the lock ---------------------------------------------
# (tests/test_requirements_lock.py already checks the lock pins every non-OCR
# requirement.)


def test_ocr_stack_is_left_out_of_the_constraints():
    """The OCR stack must stay unconstrained, so it keeps its CPU-index install."""
    assert not OCR_STACK & set(lock_pins())


def test_lock_pins_satisfy_requirements_txt():
    """A lock pin outside its requirements.txt range fails the image build.

    Catch that here, in the hermetic suite, instead of at deploy time.
    """
    pins = lock_pins()
    conflicts = []
    for req in requirements():
        pin = pins.get(canonicalize_name(req.name))
        if pin is not None and not req.specifier.contains(Version(pin.version), prereleases=True):
            conflicts.append(f"{req}: lock pins {pin.version}")
    assert conflicts == [], conflicts


def test_verify_dependency_is_a_direct_requirement():
    """`verify` imports packaging; it must not rely on arriving transitively."""
    assert "packaging" in {canonicalize_name(r.name) for r in requirements()}


# --- scripts/lock_constraints.py ----------------------------------------------


def test_constraints_cover_every_lock_pin_without_hashes():
    lock = read("requirements.lock")
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


def test_pin_emits_the_installed_local_version():
    assert installed_pin("torch", {"torch": "2.14.0+cpu"}.get) == "torch==2.14.0+cpu"
    with pytest.raises(ValueError):
        installed_pin("torch", {}.get)


def test_cuda_distributions_are_detected():
    names = ["torch", "nvidia_cublas_cu12", "NVIDIA-cudnn-cu12", "cuda-bindings", "numpy", "triton"]
    assert cuda_distributions(names) == ["cuda-bindings", "nvidia-cublas-cu12", "nvidia-cudnn-cu12"]
    assert cuda_distributions(["torch", "numpy", "docling"]) == []


def test_verify_flags_a_package_that_drifted_from_its_pin():
    """The #689 shape: the lock pins genai-prices 0.0.66, the image has 0.1.9."""
    pins = [LockedPin("genai-prices", "0.0.66"), LockedPin("fastapi", "0.138.0")]
    installed = {"genai-prices": "0.1.9", "fastapi": "0.138.0"}
    problems, checked = find_drift(pins, version_of=installed.get, marker_applies=lambda m: True)
    assert problems == ["genai-prices: installed 0.1.9, lock pins 0.0.66"]
    assert checked == 2


def test_verify_ignores_missing_packages_and_non_matching_markers():
    pins = [
        LockedPin("colorama", "0.4.6", "sys_platform == 'win32'"),
        LockedPin("not-needed", "1.0"),
        LockedPin("httpx", "0.28.1"),
    ]
    installed = {"colorama": "0.4.0", "httpx": "0.28.1"}
    problems, checked = find_drift(
        pins,
        version_of=installed.get,
        marker_applies=lambda marker: marker != "sys_platform == 'win32'",
    )
    assert problems == [] and checked == 1
