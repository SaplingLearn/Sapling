from unittest.mock import MagicMock, patch
from services.users_search import paginate_users


class TestPaginateUsers:
    def test_no_query_uses_select_with_count(self):
        # `name` now lives on user_profiles (0024); users carries only email + auth.
        users_rows = [
            {"id": "u1", "email": "enc2", "is_approved": True,
             "created_at": "2026-01-01T00:00:00Z", "last_sign_in_at": None},
        ]
        with patch("services.users_search.table") as t, \
             patch("services.users_search.get_display_names",
                   return_value={"u1": "Decrypted Name"}), \
             patch("services.users_search.decrypt_if_present",
                   side_effect=lambda v: f"d:{v}" if v else v):
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
        # name resolved off user_profiles; email decrypted off the users row.
        assert result["users"][0]["name"] == "Decrypted Name"
        assert result["users"][0]["email"] == "d:enc2"
        users_tbl.select_with_count.assert_called_once()

    def test_query_filters_after_decrypt(self):
        rows = [
            {"id": "u1", "email": "AE", "is_approved": True,
             "created_at": "x", "last_sign_in_at": None},
            {"id": "u2", "email": "BE", "is_approved": False,
             "created_at": "x", "last_sign_in_at": None},
        ]
        email_map = {"AE": "alice@bu.edu", "BE": "bob@bu.edu"}
        name_map = {"u1": "Alice Smith", "u2": "Bob Jones"}
        with patch("services.users_search.table") as t, \
             patch("services.users_search.get_display_names", return_value=name_map), \
             patch("services.users_search.decrypt_if_present",
                   side_effect=lambda v: email_map.get(v, v)):
            users_tbl = MagicMock()
            users_tbl.select.return_value = rows
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []

            def by_name(name):
                return users_tbl if name == "users" else roles_tbl

            t.side_effect = by_name

            result = paginate_users(q="alice", page=1, page_size=10)

        # Matches on the user_profiles-sourced name.
        assert result["total"] == 1
        assert len(result["users"]) == 1
        assert result["users"][0]["name"] == "Alice Smith"
        assert result["users"][0]["email"] == "alice@bu.edu"

    def test_caps_page_size(self):
        with patch("services.users_search.table") as t, \
             patch("services.users_search.get_display_names", return_value={}):
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = ([], 0)
            t.return_value = users_tbl
            result = paginate_users(q=None, page=1, page_size=9999)
        assert result["page_size"] == 200  # hard cap

    def test_attaches_roles_and_drops_orphan_joins(self):
        rows = [{"id": "u1", "email": "ENC", "is_approved": True,
                 "created_at": "x", "last_sign_in_at": None}]
        # PostgREST returns an embedded `roles` value that is None when the join
        # target was deleted but the user_roles row remained.
        join_rows = [
            {"roles": {"id": "r1", "name": "Admin", "slug": "admin", "color": "#f00",
                       "icon": None, "description": None, "is_staff_assigned": True,
                       "is_earnable": False, "display_priority": 100}},
            {"roles": None},
            {},
        ]

        with patch("services.users_search.table") as t, \
             patch("services.users_search.get_display_names", return_value={"u1": "Admin User"}), \
             patch("services.users_search.decrypt_if_present", side_effect=lambda v: v):
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = (rows, 1)
            user_roles_tbl = MagicMock()
            user_roles_tbl.select.return_value = join_rows

            def by_name(name):
                return users_tbl if name == "users" else user_roles_tbl

            t.side_effect = by_name

            result = paginate_users(q=None, page=1, page_size=50)

        assert len(result["users"]) == 1
        assert result["users"][0]["roles"] == [{
            "id": "r1", "name": "Admin", "slug": "admin", "color": "#f00",
            "icon": None, "description": None, "is_staff_assigned": True,
            "is_earnable": False, "display_priority": 100,
        }]
