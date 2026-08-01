"""Admin XP-rule editing."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestListRules:
    def test_returns_every_rule(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table") as t:
            t.return_value.select.return_value = [
                {"key": "quiz_completed", "label": "Completed a quiz",
                 "amount": 30, "enabled": True}
            ]
            r = client.get("/api/admin/xp-rules")
        assert r.json()["rules"][0]["key"] == "quiz_completed"


class TestUpdateRule:
    def test_updates_the_amount(self):
        with patch("routes.admin.require_admin"), \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action") as audit, \
             patch("routes.admin.table") as t:
            t.return_value.update.return_value = []
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={"amount": 45})
        assert r.json() == {"updated": True}
        assert t.return_value.update.call_args[0][0]["amount"] == 45
        audit.assert_called_once()

    def test_rejects_a_negative_amount(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table"):
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={"amount": -5})
        assert r.status_code == 400

    def test_rejects_an_empty_body(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table"):
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={})
        assert r.status_code == 400
