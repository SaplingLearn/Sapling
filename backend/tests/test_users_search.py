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


def _foreign_ciphertext(plaintext: str) -> str:
    """Ciphertext in the on-disk shape, sealed under a key this process lacks —
    what a row written by a backend with a different ENCRYPTION_KEY looks like."""
    import base64
    import os
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    ct = AESGCM(os.urandom(32)).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


class TestUndecryptableRows:
    """A row sealed under another ENCRYPTION_KEY must not render its ciphertext
    as the user's name/email: decrypt_if_present fails soft and hands it back."""

    def _run(self, rows, names, q=None):
        with patch("services.users_search.table") as t, \
             patch("services.users_search.get_display_names", return_value=names):
            users_tbl = MagicMock()
            users_tbl.select_with_count.return_value = (rows, len(rows))
            users_tbl.select.return_value = rows
            roles_tbl = MagicMock()
            roles_tbl.select.return_value = []
            t.side_effect = lambda name: users_tbl if name == "users" else roles_tbl
            return paginate_users(q=q, page=1, page_size=50)

    def _rows(self):
        from services.encryption import encrypt
        return [
            {"id": "u1", "email": _foreign_ciphertext("jackhe@bu.edu"), "is_approved": False,
             "created_at": "x", "last_sign_in_at": None},
            {"id": "u2", "email": encrypt("alee7@bu.edu"), "is_approved": True,
             "created_at": "x", "last_sign_in_at": None},
            # Legacy plaintext still reads through as-is.
            {"id": "u3", "email": "mober@bu.edu", "is_approved": True,
             "created_at": "x", "last_sign_in_at": None},
        ]

    def test_foreign_ciphertext_is_blanked_and_flagged(self):
        # get_display_names fails soft too: the foreign name comes back raw.
        names = {"u1": _foreign_ciphertext("Jack He"), "u2": "Aerim Lee"}
        result = self._run(self._rows(), names)
        by_id = {u["id"]: u for u in result["users"]}

        assert by_id["u1"]["email"] is None
        assert by_id["u1"]["name"] == ""
        assert by_id["u1"]["undecryptable"] is True

        assert by_id["u2"]["email"] == "alee7@bu.edu"
        assert by_id["u2"]["name"] == "Aerim Lee"
        assert by_id["u2"]["undecryptable"] is False

        assert by_id["u3"]["email"] == "mober@bu.edu"
        assert by_id["u3"]["name"] == ""
        assert by_id["u3"]["undecryptable"] is False

    def test_search_never_matches_ciphertext(self):
        rows = self._rows()
        needle = rows[0]["email"][16:24]
        result = self._run(rows, {}, q=needle)
        assert result["total"] == 0
