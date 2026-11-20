"""learning_trial is research tooling outside the request path (the within-
student trial's analysis, docs/research/learning-loop/2026-11-08-within-student-
trial-preregistration.md). Pinned in both directions, over the whole import
graph of backend/:

  - no application module reaches it, directly or through another module
    (only tests/, scripts/ and the package itself may import it); and
  - it reaches no application module: stdlib and itself only, with the GLMM
    path's numpy / pandas / statsmodels imported lazily inside a function,
    so the app venv imports every module without them; and
  - those analysis dependencies stay out of the app's requirements.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "learning_trial"
#: where an import of the package is allowed: offline tooling and tests
NOT_APP = ("tests/", "scripts/", f"{PACKAGE}/")
OPTIONAL = {"numpy", "pandas", "statsmodels", "scipy"}


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _backend_files():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("venv/", ".venv")) or "/__pycache__/" in rel:
            continue
        yield rel, path


def _imports(path: pathlib.Path, module: str) -> set[str]:
    """Dotted names `path` imports anywhere in the file (functions included):
    `from X import y` yields X and X.y; relative imports are resolved; a
    constant importlib.import_module / __import__ name counts too."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - node.level + 1] if node.level > 1 else base
                prefix = ".".join(base + ([node.module] if node.module else []))
            else:
                prefix = node.module or ""
            if prefix:
                out.add(prefix)
                out.update(f"{prefix}.{alias.name}" for alias in node.names if alias.name != "*")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and isinstance(node.args[0].value, str):
                out.add(node.args[0].value)
    return out


def _graph() -> dict[str, set[str]]:
    return {_module_name(path): _imports(path, _module_name(path)) for _, path in _backend_files()}


def _is_package_module(name: str) -> bool:
    return name == PACKAGE or name.startswith(PACKAGE + ".")


def test_no_application_module_reaches_learning_trial():
    graph = _graph()
    reaches = {name for name in graph if _is_package_module(name)}
    changed = True
    while changed:  # every module that imports, directly or transitively, the package
        changed = False
        for name, imported in graph.items():
            if name not in reaches and any(i in reaches or _is_package_module(i) for i in imported):
                reaches.add(name)
                changed = True
    paths = {_module_name(p): rel for rel, p in _backend_files()}
    offenders = sorted(paths[name] for name in reaches if not paths[name].startswith(NOT_APP))
    assert not offenders, f"application modules reach {PACKAGE}: {offenders}"
    assert "scripts.export_learning_trial" in reaches, "the scan must see the exporter's import"


def test_learning_trial_imports_only_the_stdlib_and_itself():
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    offenders = []
    for path in sorted((BACKEND / PACKAGE).glob("*.py")):
        module = _module_name(path)
        for name in _imports(path, module):
            root = name.split(".")[0]
            if root in stdlib or root == PACKAGE:
                continue
            if root in OPTIONAL and path.name == "glmm.py":
                continue
            offenders.append(f"{path.name} imports {name}")
    assert not offenders, offenders


def test_the_glmm_dependencies_are_imported_lazily():
    """Module level: stdlib and the package only; the analysis extra is imported
    inside a function, so `import learning_trial.glmm` works in the app venv."""
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    tree = ast.parse((BACKEND / PACKAGE / "glmm.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    roots = {
        (alias.name if isinstance(n, ast.Import) else (n.module or "")).split(".")[0]
        for n in top
        for alias in n.names
    }
    assert roots <= stdlib | {PACKAGE}, roots


def test_every_module_imports_without_the_analysis_extra():
    """In a fresh interpreter where numpy, pandas, scipy and statsmodels cannot
    be imported, every module of the package still imports."""
    modules = [_module_name(p) for p in sorted((BACKEND / PACKAGE).glob("*.py"))]
    code = (
        "import importlib, sys\n"
        f"for name in {sorted(OPTIONAL)!r}:\n"
        "    sys.modules[name] = None\n"
        f"for module in {modules!r}:\n"
        "    importlib.import_module(module)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("dependency", ["statsmodels", "pandas"])
def test_the_analysis_extra_is_not_an_app_requirement(dependency):
    for name in ("requirements.txt", "requirements.lock"):
        text = (BACKEND / name).read_text(encoding="utf-8").lower()
        lines = [line.split("#")[0].strip() for line in text.splitlines()]
        assert not any(line.startswith(dependency) for line in lines), f"{dependency} in {name}"
    assert dependency in (BACKEND / "requirements-analysis.txt").read_text(encoding="utf-8")
