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


# ── apply_curve ───────────────────────────────────────────────────────────────

class TestApplyCurve:
    def test_at_mean_returns_avg_target(self):
        result = apply_curve(0.68, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.83) < 1e-9

    def test_one_sd_above_mean(self):
        result = apply_curve(0.80, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.93) < 1e-9

    def test_one_sd_below_mean(self):
        result = apply_curve(0.56, class_mean=0.68, class_sd=0.12,
                             avg_target=0.83, sd_delta=0.10)
        assert abs(result - 0.73) < 1e-9

    def test_clamp_above_100(self):
        result = apply_curve(1.0, class_mean=0.50, class_sd=0.05,
                             avg_target=0.83, sd_delta=0.10)
        assert result == 1.0

    def test_clamp_below_0(self):
        result = apply_curve(0.0, class_mean=0.80, class_sd=0.05,
                             avg_target=0.50, sd_delta=0.15)
        assert result == 0.0

    def test_sd_zero_returns_raw_score(self):
        result = apply_curve(0.75, class_mean=0.75, class_sd=0.0,
                             avg_target=0.83, sd_delta=0.10)
        assert result == 0.75

    def test_negative_sd_returns_raw_score(self):
        # Negative SD is mathematically invalid — treated same as zero
        result = apply_curve(0.75, class_mean=0.75, class_sd=-0.05,
                             avg_target=0.83, sd_delta=0.10)
        assert result == 0.75


class TestCategoryGradeCurved:
    ITEMS = [
        {"id": "a1", "points_possible": "100", "points_earned": "80",
         "curve_class_mean": 0.68, "curve_class_sd": 0.12,
         "curve_avg_target": None, "curve_sd_delta": None},
        {"id": "a2", "points_possible": "100", "points_earned": "60",
         "curve_class_mean": 0.55, "curve_class_sd": 0.10,
         "curve_avg_target": None, "curve_sd_delta": None},
    ]

    def test_raw_mode_ignores_curve(self):
        result = category_grade(self.ITEMS, curve_mode="raw",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        # points-weighted: (80+60)/(100+100) = 0.70 (equal points → same as mean)
        assert abs(result - 0.70) < 1e-9

    def test_curved_mode_applies_curve(self):
        # a1: z=(0.80-0.68)/0.12=1.0 → 0.83+0.10=0.93 → 0.93*100=93 earned-equiv
        # a2: z=(0.60-0.55)/0.10=0.5 → 0.83+0.05=0.88 → 0.88*100=88 earned-equiv
        # points-weighted: (93+88)/(100+100) = 0.905 (equal points → same as mean)
        result = category_grade(self.ITEMS, curve_mode="curved",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        assert abs(result - 0.905) < 1e-9

    def test_curved_skips_items_without_curve_data(self):
        items = [
            {"id": "a1", "points_possible": "100", "points_earned": "80",
             "curve_class_mean": None, "curve_class_sd": None,
             "curve_avg_target": None, "curve_sd_delta": None},
        ]
        result = category_grade(items, curve_mode="curved",
                                curve_avg_target=0.83, curve_sd_delta=0.10)
        # No curve data → raw score used
        assert abs(result - 0.80) < 1e-9


