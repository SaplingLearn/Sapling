from unittest.mock import MagicMock, patch
from services.admin_audit import log_admin_action


class TestLogAdminAction:
    def test_inserts_row_with_all_fields(self):
        with patch("services.admin_audit.table") as t:
            inserted = MagicMock()
            t.return_value.insert = inserted
            log_admin_action(
                actor_id="admin1",
                action="user.approve",
                target_type="user",
                target_id="u1",
                payload={"note": "manual"},
            )

        assert t.called
        assert t.call_args.args[0] == "admin_audit_log"
        inserted.assert_called_once()
        row = inserted.call_args.args[0]
        assert row["actor_id"] == "admin1"
        assert row["action"] == "user.approve"
        assert row["target_type"] == "user"
        assert row["target_id"] == "u1"
        assert row["payload"] == {"note": "manual"}

    def test_swallows_db_errors_so_main_action_still_succeeds(self):
        with patch("services.admin_audit.table") as t:
            t.return_value.insert.side_effect = RuntimeError("network")
            log_admin_action(
                actor_id="admin1",
                action="user.approve",
                target_type="user",
                target_id="u1",
            )  # must not raise
