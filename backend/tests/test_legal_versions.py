"""The Terms / Privacy Policy versions are one fact kept in two places: the
backend refuses an onboarding submit that accepted anything else
(services/legal.py), and the frontend shows the documents and their dates from
frontend/src/lib/legal/versions.ts. If they drift, every new student is
refused with `legal_outdated` (or the pages show one date while the backend
records another), so this pins them together."""
import re
from pathlib import Path

import pytest

from services import legal

VERSIONS_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "legal" / "versions.ts"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ts_constant(src: str, name: str) -> str | None:
    m = re.search(rf'export\s+const\s+{name}\s*(?::\s*string\s*)?=\s*["\']([^"\']+)["\']', src)
    return m.group(1) if m else None


def test_backend_versions_are_dates():
    """A version is the document's "Last updated" date."""
    assert _DATE.match(legal.TERMS_VERSION)
    assert _DATE.match(legal.PRIVACY_VERSION)


def test_frontend_and_backend_versions_match():
    if not VERSIONS_TS.exists():
        pytest.skip(
            f"{VERSIONS_TS} does not exist in this checkout (the frontend's "
            "legal versions module lands with the onboarding frontend change); "
            "nothing to compare services/legal.py against yet"
        )
    src = VERSIONS_TS.read_text()
    assert _ts_constant(src, "TERMS_VERSION") == legal.TERMS_VERSION, (
        f"TERMS_VERSION differs: {VERSIONS_TS.name} says "
        f"{_ts_constant(src, 'TERMS_VERSION')!r}, services/legal.py says {legal.TERMS_VERSION!r}"
    )
    assert _ts_constant(src, "PRIVACY_VERSION") == legal.PRIVACY_VERSION, (
        f"PRIVACY_VERSION differs: {VERSIONS_TS.name} says "
        f"{_ts_constant(src, 'PRIVACY_VERSION')!r}, services/legal.py says {legal.PRIVACY_VERSION!r}"
    )


@pytest.mark.parametrize("src,expected", [
    ('export const TERMS_VERSION = "2026-10-22";', "2026-10-22"),
    ("export const TERMS_VERSION = '2026-10-22'", "2026-10-22"),
    ('export const TERMS_VERSION: string = "2026-10-22";', "2026-10-22"),
    ('export const OTHER = "2026-10-22";', None),
])
def test_the_frontend_constant_is_read_as_written(src, expected):
    assert _ts_constant(src, "TERMS_VERSION") == expected


def test_accepted_current_needs_both():
    assert legal.accepted_current(legal.TERMS_VERSION, legal.PRIVACY_VERSION)
    assert not legal.accepted_current(legal.TERMS_VERSION, "2000-01-01")
    assert not legal.accepted_current("2000-01-01", legal.PRIVACY_VERSION)
