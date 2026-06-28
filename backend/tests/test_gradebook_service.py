"""Unit tests for services.gradebook_service."""
import pytest

from services import gradebook_service as svc
from services.gradebook_service import apply_curve, category_grade


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
        # points-weighted: (92+40)/(100+50) = 132/150 ≈ 0.88
        assert svc.category_grade(items) == pytest.approx(132 / 150)

    def test_higher_point_assignments_carry_more_weight(self):
        items = [
            {"points_possible": 100, "points_earned": 92},  # 92%
            {"points_possible": 10,  "points_earned": 5},   # 50%
        ]
        # points-weighted: (92+5)/(100+10) = 97/110 ≈ 0.8818
        # unweighted mean would give (0.92+0.50)/2 = 0.71 — wrong
        assert svc.category_grade(items) == pytest.approx(97 / 110)

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


# ── letter_for ───────────────────────────────────────────────────────────────

class TestLetterFor:
    def test_uses_default_scale_when_none_provided(self):
        assert svc.letter_for(95.0, None) == "A"
        assert svc.letter_for(91.0, None) == "A-"
        assert svc.letter_for(72.5, None) == "C-"
        assert svc.letter_for(40.0, None) == "F"

    def test_returns_none_when_grade_is_none(self):
        assert svc.letter_for(None, None) is None

    def test_uses_custom_scale_when_provided(self):
        # A custom course where 90+ is an A and there is no minus tier.
        scale = [{"min": 90, "letter": "A"}, {"min": 80, "letter": "B"}, {"min": 0, "letter": "F"}]
        assert svc.letter_for(95.0, scale) == "A"
        assert svc.letter_for(85.0, scale) == "B"
        assert svc.letter_for(50.0, scale) == "F"

    def test_handles_boundary_exactly(self):
        assert svc.letter_for(93.0, None) == "A"
        assert svc.letter_for(92.999, None) == "A-"


# ── drop-lowest ──────────────────────────────────────────────────────────────

class TestDropLowest:
    def test_drops_single_lowest_ratio_item(self):
        items = [
            {"points_possible": 100, "points_earned": 100},  # ratio 1.0
            {"points_possible": 100, "points_earned": 50},   # ratio 0.5 (dropped)
            {"points_possible": 100, "points_earned": 90},   # ratio 0.9
        ]
        # Keep 100/100 and 90/100 → 190/200 = 0.95
        assert svc.category_grade(items, drop_lowest=1) == pytest.approx(0.95)

    def test_drop_lowest_uses_ratio_not_absolute_points(self):
        items = [
            {"points_possible": 10,  "points_earned": 1},    # ratio 0.10 (worst, dropped)
            {"points_possible": 100, "points_earned": 60},   # ratio 0.60
        ]
        # Drop the 1/10 (ratio 0.1) even though it's fewer absolute points.
        assert svc.category_grade(items, drop_lowest=1) == pytest.approx(0.60)

    def test_drop_lowest_ge_count_returns_none(self):
        items = [{"points_possible": 100, "points_earned": 80}]
        assert svc.category_grade(items, drop_lowest=1) is None
        assert svc.category_grade(items, drop_lowest=5) is None

    def test_drop_lowest_via_current_grade(self):
        cats = [{"id": "hw", "name": "HW", "weight": 100, "sort_order": 0, "drop_lowest": 1}]
        assignments = [
            {"category_id": "hw", "points_possible": 100, "points_earned": 100},
            {"category_id": "hw", "points_possible": 100, "points_earned": 60},
            {"category_id": "hw", "points_possible": 100, "points_earned": 80},
        ]
        # Drop the 60 → (100+80)/(200) = 0.9 → 90.0
        assert svc.current_grade(cats, assignments) == pytest.approx(90.0)


# ── apply_curve ──────────────────────────────────────────────────────────────

class TestApplyCurve:
    def test_recenters_on_target_keeping_relative_position(self):
        # raw 70, class mean 60 sd 10, target 75, sd_delta 0 → new_sd=10
        # curved = 75 + (70-60) * (10/10) = 85
        out = svc.apply_curve(70.0, class_mean=60.0, class_sd=10.0,
                              avg_target=75.0, sd_delta=0.0)
        assert out == pytest.approx(85.0)

    def test_sd_delta_tightens_spread(self):
        # new_sd = 10 + (-5) = 5; curved = 75 + (70-60)*(5/10) = 80
        out = svc.apply_curve(70.0, class_mean=60.0, class_sd=10.0,
                              avg_target=75.0, sd_delta=-5.0)
        assert out == pytest.approx(80.0)

    def test_clamps_to_0_100(self):
        out = svc.apply_curve(100.0, class_mean=50.0, class_sd=5.0,
                              avg_target=90.0, sd_delta=0.0)
        assert out == 100.0
        low = svc.apply_curve(10.0, class_mean=80.0, class_sd=5.0,
                              avg_target=70.0, sd_delta=0.0)
        assert low == 0.0

    def test_falls_back_to_raw_when_sd_missing_or_zero(self):
        assert svc.apply_curve(70.0, class_mean=60.0, class_sd=0.0,
                               avg_target=75.0, sd_delta=0.0) == 70.0
        assert svc.apply_curve(70.0, class_mean=60.0, class_sd=None,
                               avg_target=75.0, sd_delta=0.0) == 70.0

    def test_falls_back_to_raw_when_target_or_mean_missing(self):
        assert svc.apply_curve(70.0, class_mean=60.0, class_sd=10.0,
                               avg_target=None, sd_delta=0.0) == 70.0
        assert svc.apply_curve(70.0, class_mean=None, class_sd=10.0,
                               avg_target=75.0, sd_delta=0.0) == 70.0

    def test_none_percent_returns_none(self):
        assert svc.apply_curve(None, class_mean=60.0, class_sd=10.0,
                               avg_target=75.0, sd_delta=0.0) is None


class TestCurrentGradeCurved:
    def test_curved_mode_uses_assignment_class_stats(self):
        cats = [{"id": "exams", "name": "Exams", "weight": 100, "sort_order": 0,
                 "drop_lowest": 0}]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 70,
             "curve_class_mean": 60.0, "curve_class_sd": 10.0},
        ]
        # raw = 70; curved = 80 + (70-60)*(10/10) = 90
        out = svc.current_grade(cats, assignments, curve_mode="curved",
                                curve_avg_target=80.0, curve_sd_delta=0.0)
        assert out == pytest.approx(90.0)

    def test_raw_mode_ignores_curve_targets(self):
        cats = [{"id": "exams", "name": "Exams", "weight": 100, "sort_order": 0}]
        assignments = [
            {"category_id": "exams", "points_possible": 100, "points_earned": 70,
             "curve_class_mean": 60.0, "curve_class_sd": 10.0},
        ]
        out = svc.current_grade(cats, assignments, curve_mode="raw",
                                curve_avg_target=80.0, curve_sd_delta=0.0)
        assert out == pytest.approx(70.0)


# ── GPA ──────────────────────────────────────────────────────────────────────

class TestGpa:
    def test_gpa_points_default_scale(self):
        assert svc.gpa_points(95.0) == pytest.approx(4.0)
        assert svc.gpa_points(91.0) == pytest.approx(3.7)   # A-
        assert svc.gpa_points(80.0) == pytest.approx(2.7)   # B-
        assert svc.gpa_points(40.0) == pytest.approx(0.0)   # F

    def test_gpa_points_none_when_no_grade(self):
        assert svc.gpa_points(None) is None

    def test_weighted_gpa_credit_weighted(self):
        # Hand-computed transcript fixture:
        #   CS161   3 credits, 90% → A- → 3.7
        #   MATH200 4 credits, 80% → B- → 2.7
        #   GPA = (3.7*3 + 2.7*4) / (3+4) = 21.9 / 7 = 3.1285714...
        grades = [
            {"grade_points": svc.gpa_points(90.0), "credits": 3},
            {"grade_points": svc.gpa_points(80.0), "credits": 4},
        ]
        assert svc.weighted_gpa(grades) == pytest.approx(3.1285714, rel=1e-4)

    def test_weighted_gpa_skips_ungraded(self):
        grades = [
            {"grade_points": 4.0, "credits": 3},
            {"grade_points": None, "credits": 4},   # ungraded — skipped
        ]
        assert svc.weighted_gpa(grades) == pytest.approx(4.0)

    def test_weighted_gpa_none_when_nothing_graded(self):
        assert svc.weighted_gpa([{"grade_points": None, "credits": 3}]) is None

    def test_weighted_gpa_defaults_credits_to_one(self):
        # 4.0 (1 credit default) and 2.0 (1 credit default) → 3.0
        grades = [
            {"grade_points": 4.0, "credits": None},
            {"grade_points": 2.0, "credits": 0},
        ]
        assert svc.weighted_gpa(grades) == pytest.approx(3.0)
