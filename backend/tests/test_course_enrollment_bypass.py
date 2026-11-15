"""The hermetic suite's #115 enrollment bypass (`conftest._bypass_course_enrollment`).

One `monkeypatch.setattr` on `academics.enrolled_offering_for_course` must
cover every importer of `require_course_enrollment` — the routes import the
gate by name, and the gate looks its one read up as a module global — and the
`real_course_enrollment` marker must switch it off.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services import academics
from tests.conftest import BYPASS_OFFERING_ID


def test_the_gate_passes_through_every_importer_without_a_read():
    import routes.documents
    import services.tutor.course
    import routes.notes

    with patch("services.academics.resolve_offering", return_value=None), \
         patch("services.academics.table") as t:
        for gate in (academics.require_course_enrollment,
                     routes.documents.require_course_enrollment,
                     services.tutor.course.require_course_enrollment,
                     routes.notes.require_course_enrollment):
            assert gate("u1", "c-anything") == BYPASS_OFFERING_ID
    t.assert_not_called()


def test_the_bypass_keeps_the_pre_115_current_term_resolution():
    with patch("services.academics.resolve_offering", return_value="off-current") as ro:
        assert academics.require_course_enrollment("u1", "c1") == "off-current"
    ro.assert_called_once_with("c1", create=True)


@pytest.mark.real_course_enrollment
def test_the_marker_runs_the_real_gate():
    with patch("services.academics.table") as t:
        t.return_value.select.return_value = []
        with pytest.raises(Exception) as exc:
            academics.require_course_enrollment("u1", "c1")
    assert getattr(exc.value, "status_code", None) == 404
    t.assert_called_once_with("enrollments")
