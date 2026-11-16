import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import config
import routes.auth as auth


def test_default_allows_bu_edu(monkeypatch):
    monkeypatch.setattr("services.auth.signin.ALLOWED_EMAIL_DOMAINS", ["bu.edu"])
    assert auth._email_domain_allowed("student@bu.edu") is True
    assert auth._email_domain_allowed("someone@gmail.com") is False


def test_case_insensitive(monkeypatch):
    monkeypatch.setattr("services.auth.signin.ALLOWED_EMAIL_DOMAINS", ["bu.edu"])
    assert auth._email_domain_allowed("Student@BU.EDU") is True


def test_multiple_domains(monkeypatch):
    monkeypatch.setattr("services.auth.signin.ALLOWED_EMAIL_DOMAINS", ["bu.edu", "saplinglearn.com"])
    assert auth._email_domain_allowed("dev@saplinglearn.com") is True
    assert auth._email_domain_allowed("x@bu.edu") is True
    assert auth._email_domain_allowed("x@other.com") is False


def test_empty_allowlist_allows_any(monkeypatch):
    monkeypatch.setattr("services.auth.signin.ALLOWED_EMAIL_DOMAINS", [])
    assert auth._email_domain_allowed("anyone@example.com") is True


@pytest.mark.parametrize(
    ("app_env", "raw", "expected"),
    [
        ("local", None, []),
        ("production", None, ["bu.edu"]),
        ("staging", None, ["bu.edu"]),
        ("test", None, ["bu.edu"]),
        ("dev", None, ["bu.edu"]),
        ("local", "bu.edu", ["bu.edu"]),
        ("production", "", []),
        ("local", " @BU.EDU, saplinglearn.com ", ["bu.edu", "saplinglearn.com"]),
    ],
)
def test_domain_config_defaults_and_overrides(app_env, raw, expected):
    assert config.parse_allowed_email_domains(raw, app_env) == expected


def test_import_time_allowlist_follows_app_env():
    """One subprocess for the wiring: config reads APP_ENV and the unset
    variable at import, isolated from the developer's .env."""
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1"}
    env.pop("ALLOWED_EMAIL_DOMAINS", None)
    script = (
        "import importlib, json, os, config\n"
        "out = {}\n"
        "for app_env in ('local', 'production'):\n"
        "    os.environ['APP_ENV'] = app_env\n"
        "    out[app_env] = importlib.reload(config).ALLOWED_EMAIL_DOMAINS\n"
        "os.environ.pop('APP_ENV')\n"
        "out['unset'] = importlib.reload(config).ALLOWED_EMAIL_DOMAINS\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "local": [], "production": ["bu.edu"], "unset": ["bu.edu"],
    }
