"""Unit tests for services.profiles — display-name reads off user_profiles.

After migration 0024 the public display `name` lives on `user_profiles`
(1:1 with users, PK/FK user_id) and is 🔒 encrypted. These helpers read it
back and decrypt it for cross-domain callers that used to read users.name.
"""
from unittest.mock import patch

from services import profiles


class TestGetDisplayName:
    def test_decrypts_present_row(self):
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present",
            side_effect=lambda v: f"d:{v}" if v else v,
        ):
            t.return_value.select.return_value = [{"name": "ENC"}]
            assert profiles.get_display_name("u1") == "d:ENC"

    def test_returns_empty_when_row_absent(self):
        with patch("services.profiles.table") as t:
            t.return_value.select.return_value = []
            assert profiles.get_display_name("u1") == ""

    def test_returns_empty_when_name_is_none(self):
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = [{"name": None}]
            assert profiles.get_display_name("u1") == ""

    def test_filters_by_user_id(self):
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = [{"name": "X"}]
            profiles.get_display_name("u42")
            _, kwargs = t.return_value.select.call_args
            assert kwargs["filters"] == {"user_id": "eq.u42"}


class TestGetDisplayNames:
    def test_bulk_maps_decrypted_names(self):
        rows = [{"user_id": "u1", "name": "AENC"}, {"user_id": "u2", "name": "BENC"}]
        decrypt_map = {"AENC": "Alice", "BENC": "Bob"}
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present",
            side_effect=lambda v: decrypt_map.get(v, v),
        ):
            t.return_value.select.return_value = rows
            out = profiles.get_display_names(["u1", "u2"])
        assert out == {"u1": "Alice", "u2": "Bob"}

    def test_missing_rows_omitted(self):
        rows = [{"user_id": "u1", "name": "AENC"}]
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = rows
            out = profiles.get_display_names(["u1", "u2"])
        assert out == {"u1": "AENC"}
        assert "u2" not in out

    def test_empty_input_skips_query(self):
        with patch("services.profiles.table") as t:
            out = profiles.get_display_names([])
        assert out == {}
        t.assert_not_called()

    def test_dedups_ids_in_query(self):
        with patch("services.profiles.table") as t, patch(
            "services.profiles.decrypt_if_present", side_effect=lambda v: v
        ):
            t.return_value.select.return_value = []
            profiles.get_display_names(["u1", "u1", "u2"])
            _, kwargs = t.return_value.select.call_args
            flt = kwargs["filters"]["user_id"]
            # in.(...) with each id once
            assert flt.startswith("in.(")
            ids = flt[len("in.(") : -1].split(",")
            assert sorted(ids) == ["u1", "u2"]
