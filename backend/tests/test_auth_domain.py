import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import routes.auth as auth


def test_default_allows_bu_edu(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", ["bu.edu"])
    assert auth._email_domain_allowed("student@bu.edu") is True
    assert auth._email_domain_allowed("someone@gmail.com") is False


def test_case_insensitive(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", ["bu.edu"])
    assert auth._email_domain_allowed("Student@BU.EDU") is True


def test_multiple_domains(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", ["bu.edu", "saplinglearn.com"])
    assert auth._email_domain_allowed("dev@saplinglearn.com") is True
    assert auth._email_domain_allowed("x@bu.edu") is True
    assert auth._email_domain_allowed("x@other.com") is False


def test_empty_allowlist_allows_any(monkeypatch):
    monkeypatch.setattr(auth, "ALLOWED_EMAIL_DOMAINS", [])
    assert auth._email_domain_allowed("anyone@example.com") is True


@pytest.mark.parametrize(("app_env", "expected"), [("local", []), ("production", ["bu.edu"]), ("staging", ["bu.edu"])])
def test_environment_default_domain_allowlist(app_env, expected):
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "APP_ENV": app_env}
    env.pop("ALLOWED_EMAIL_DOMAINS", None)
    result = subprocess.run([sys.executable, "-c", "import config,json; print(json.dumps(config.ALLOWED_EMAIL_DOMAINS))"],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == expected
