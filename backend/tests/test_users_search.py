from unittest.mock import MagicMock, patch
from services.users_search import paginate_users


class TestPaginateUsers:
    def test_no_query_uses_select_with_count(self):
        users_rows = [
            {"id": "u1", "name": "enc1", "email": "enc2", "is_approved": True,
             "created_at": "2026-01-01T00:00:00Z", "last_sign_in_at": None},
        ]
        with patch("services.users_search.table") as t, \
             patch("services.users_search.decrypt_if_present", side_effect=lambda v: f"d:{v}" if v else v):
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = (users_rows, 137)
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []

            def by_name(name):
                return users_tbl if name == "users" else roles_tbl

            t.side_effect = by_name

            result = paginate_users(q=None, page=1, page_size=50)

        assert result["total"] == 137
        assert result["page"] == 1
        assert result["page_size"] == 50
        assert result["users"][0]["name"] == "d:enc1"
        users_tbl.select_with_count.assert_called_once()

    def test_query_filters_after_decrypt(self):
        rows = [
            {"id": "u1", "name": "ALICE_ENC", "email": "AE", "is_approved": True,
             "created_at": "x", "last_sign_in_at": None},
            {"id": "u2", "name": "BOB_ENC", "email": "BE", "is_approved": False,
             "created_at": "x", "last_sign_in_at": None},
        ]
        decrypt_map = {"ALICE_ENC": "Alice Smith", "AE": "alice@bu.edu",
                       "BOB_ENC": "Bob Jones", "BE": "bob@bu.edu"}
        with patch("services.users_search.table") as t, \
             patch("services.users_search.decrypt_if_present", side_effect=lambda v: decrypt_map.get(v, v)):
            users_tbl = MagicMock()
            users_tbl.select.return_value = rows
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []

            def by_name(name):
                return users_tbl if name == "users" else roles_tbl

            t.side_effect = by_name

            result = paginate_users(q="alice", page=1, page_size=10)

        assert result["total"] == 1
        assert len(result["users"]) == 1
        assert result["users"][0]["email"] == "alice@bu.edu"

    def test_caps_page_size(self):
        with patch("services.users_search.table") as t:
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = ([], 0)
            t.return_value = users_tbl
            result = paginate_users(q=None, page=1, page_size=9999)
        assert result["page_size"] == 200  # hard cap
