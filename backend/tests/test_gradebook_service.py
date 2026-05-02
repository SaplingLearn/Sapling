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


# ── current_grade ────────────────────────────────────────────────────────────

class TestCurrentGrade:
    def _cat(self, id_: str, weight: float) -> dict:
        return {"id": id_, "name": id_, "weight": weight, "sort_order": 0}

    def test_returns_none_when_no_graded_categories(self):
        cats = [self._cat("exams", 50), self._cat("psets", 50)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": None},
        ]
        assert svc.current_grade(cats, assignments) is None

    def test_normalizes_when_some_categories_ungraded(self):
        cats = [self._cat("exams", 50), self._cat("psets", 50)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 90},
            # psets has no graded items — drops out, exams gets full weight.
        ]
        # category_grade(exams) = 0.9; only contributing weight; 0.9 * 100 = 90
        assert svc.current_grade(cats, assignments) == pytest.approx(90.0)

    def test_weighted_average_across_categories(self):
        cats = [self._cat("exams", 60), self._cat("psets", 40)]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 80},
            {"category_id": "psets", "points_possible": 100, "points_earned": 100},
        ]
        # (0.8*60 + 1.0*40) / (60+40) = 88 → ×100
        assert svc.current_grade(cats, assignments) == pytest.approx(88.0)

    def test_ignores_assignments_without_a_category(self):
        cats = [self._cat("exams", 100)]
        assignments = [
            {"category_id": None,    "points_possible": 100, "points_earned": 50},
            {"category_id": "exams", "points_possible": 100, "points_earned": 90},
        ]
        assert svc.current_grade(cats, assignments) == pytest.approx(90.0)
