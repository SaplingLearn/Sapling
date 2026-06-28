from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUpdateScoping:
    def test_404_when_assignment_not_in_user_enrollments(self):
        tables = {
            "assignments": _tbl(select=[]),  # no row owned by user's enrollments
        }
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.patch("/api/calendar/assignments/a-other",
                             json={"user_id": "user_andres", "title": "x"})
        assert r.status_code == 404

    def test_updates_owned_assignment(self):
        tables = {"assignments": _tbl(select=[{"id": "a1"}], update=[])}
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.patch("/api/calendar/assignments/a1",
                             json={"user_id": "user_andres", "title": "new"})
        assert r.status_code == 200
        assert r.json() == {"updated": True}
