"""Unit tests for services.gradebook_service."""
import pytest

from services import gradebook_service as svc


# ── category_grade ───────────────────────────────────────────────────────────

class TestCategoryGrade:
    def test_returns_none_when_no_graded_items(self):
        assert svc.category_grade([]) is None

    def test_returns_none_when_only_ungraded_items(self):
        items = [
            {"points_possible": 100, "points_earned": None},
            {"points_possible": 50,  "points_earned": None},
        ]
        assert svc.category_grade(items) is None

    def test_averages_points_earned_over_points_possible(self):
        items = [
            {"points_possible": 100, "points_earned": 92},
            {"points_possible": 50,  "points_earned": 40},
        ]
        # (92 + 40) / (100 + 50) = 0.88
        assert svc.category_grade(items) == pytest.approx(0.88)

    def test_skips_items_missing_points_possible(self):
        items = [
            {"points_possible": None, "points_earned": 100},
            {"points_possible": 100,  "points_earned": 80},
        ]
        assert svc.category_grade(items) == pytest.approx(0.80)

    def test_allows_extra_credit(self):
        items = [{"points_possible": 100, "points_earned": 110}]
        assert svc.category_grade(items) == pytest.approx(1.10)
