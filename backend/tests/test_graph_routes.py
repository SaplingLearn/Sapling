"""
Unit tests for routes/graph.py
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestGraphRoutes:
    def test_get_user_graph_returns_500_on_failure(self):
        with patch("routes.graph.get_graph", side_effect=Exception("graph failed")):
            r = client.get("/api/graph/user_andres")

        assert r.status_code == 500
        assert r.json() == {"detail": "graph failed"}

    def test_get_user_recommendations_returns_500_on_failure(self):
        with patch("routes.graph.get_recommendations", side_effect=Exception("recommendations failed")):
            r = client.get("/api/graph/user_andres/recommendations")

        assert r.status_code == 500
        assert r.json() == {"detail": "recommendations failed"}
