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
