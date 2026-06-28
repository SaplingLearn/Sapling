# tests/test_academics_enrollment_resolver.py
from unittest.mock import MagicMock, patch
import services.academics as ac

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUserEnrollmentIds:
    def test_returns_rows(self):
        with patch("services.academics.table", side_effect=_dispatch({
            "enrollments": _tbl(select=[{"id": "e1", "offering_id": "o1"}]),
        })):
            assert ac.user_enrollment_ids("user_andres") == [{"id": "e1", "offering_id": "o1"}]

    def test_empty_user(self):
        assert ac.user_enrollment_ids("") == []

class TestEnrollmentIdFor:
    def test_existing_enrollment_current_term(self):
        # user_offering_ids_for_course -> ["o1"]; term match; enrollment e1
        tables = {
            "course_offerings": _tbl(select=[{"id": "o1"}]),
            "enrollments": _tbl(select=[{"id": "e1"}]),
        }
        with patch("services.academics.table", side_effect=_dispatch(tables)), \
             patch("services.academics.user_offering_ids_for_course", return_value=["o1"]), \
             patch("services.academics.current_term", return_value=None):
            assert ac.enrollment_id_for("user_andres", "CS101") == "e1"

    def test_create_when_missing(self):
        with patch("services.academics.user_offering_ids_for_course", return_value=[]), \
             patch("services.academics.resolve_offering", return_value="o9"), \
             patch("services.academics.table", side_effect=_dispatch({
                 "enrollments": _tbl(select=[], insert=[]),
             })):
            eid = ac.enrollment_id_for("user_andres", "CS101", create=True)
            assert isinstance(eid, str) and eid

    def test_missing_no_create_returns_none(self):
        with patch("services.academics.user_offering_ids_for_course", return_value=[]):
            assert ac.enrollment_id_for("user_andres", "CS101", create=False) is None
