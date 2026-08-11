"""Unit tests for services/growth.py — the level curve from growth_stages."""
import pytest
from unittest.mock import patch

STAGE_ROWS = [
    {"slug": "bare", "name": "Bare Soil", "blurb": "b", "min_level": 1, "xp_to_complete": 200, "sort_order": 0},
    {"slug": "soil", "name": "Fallow Soil", "blurb": "b", "min_level": 5, "xp_to_complete": 300, "sort_order": 1},
    {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10, "xp_to_complete": 500, "sort_order": 2},
    {"slug": "sprout", "name": "Sprout", "blurb": "b", "min_level": 15, "xp_to_complete": 800, "sort_order": 3},
    {"slug": "old", "name": "Old Growth", "blurb": "b", "min_level": 20, "xp_to_complete": None, "sort_order": 4},
]


@pytest.fixture(autouse=True)
def _stub_stages():
    with patch("services.growth.table") as t:
        t.return_value.select.return_value = STAGE_ROWS
        from services.growth import clear_growth_cache
        clear_growth_cache()
        yield t
        clear_growth_cache()


class TestXpForLevel:
    def test_first_band_divides_by_its_span(self):
        # Bare Soil spans levels 1-5 => 4 levels, 200 XP => 50 each.
        from services.growth import xp_for_level
        assert xp_for_level(1) == 50
        assert xp_for_level(4) == 50

    def test_band_boundary_uses_the_new_band(self):
        # Level 5 is the first level of Fallow Soil: 300 / 5 = 60.
        from services.growth import xp_for_level
        assert xp_for_level(5) == 60

    def test_terminal_stage_costs_nothing(self):
        from services.growth import xp_for_level
        assert xp_for_level(20) == 0
        assert xp_for_level(99) == 0


class TestLevelForXp:
    def test_zero_xp_is_level_one(self):
        from services.growth import level_for_xp
        assert level_for_xp(0) == 1

    def test_just_short_of_a_level_does_not_advance(self):
        from services.growth import level_for_xp
        assert level_for_xp(49) == 1

    def test_exact_threshold_advances(self):
        from services.growth import level_for_xp
        assert level_for_xp(50) == 2

    def test_completing_the_first_band_reaches_level_five(self):
        from services.growth import level_for_xp
        assert level_for_xp(200) == 5

    def test_caps_at_the_terminal_level(self):
        from services.growth import level_for_xp
        # 200 + 300 + 500 + 800 = 1800 reaches level 20 and stops there.
        assert level_for_xp(1800) == 20
        assert level_for_xp(999_999) == 20


class TestRoundTrip:
    def test_level_for_xp_inverts_xp_for_level(self):
        from services.growth import level_for_xp, xp_for_level
        total = 0
        for level in range(1, 20):
            assert level_for_xp(total) == level
            total += xp_for_level(level)
        assert level_for_xp(total) == 20


class TestXpIntoLevel:
    def test_reports_progress_within_the_band(self):
        from services.growth import xp_into_level
        assert xp_into_level(70) == (20, 50)   # 50 spent on L1->2, 20 into L2

    def test_terminal_level_reports_zero_of_zero(self):
        from services.growth import xp_into_level
        assert xp_into_level(5000) == (0, 0)


class TestStageForLevel:
    def test_picks_the_containing_band(self):
        from services.growth import stage_for_level
        assert stage_for_level(1)["slug"] == "bare"
        assert stage_for_level(4)["slug"] == "bare"
        assert stage_for_level(5)["slug"] == "soil"
        assert stage_for_level(17)["slug"] == "sprout"

    def test_above_the_last_threshold_is_terminal(self):
        from services.growth import stage_for_level
        assert stage_for_level(50)["slug"] == "old"


# sort_order and min_level are independent columns (20260731193214_gamification.sql has no
# constraint tying them) that merely happen to agree in the current seed. These rows
# are fetched in sort_order order (soil before bare) but disagree with min_level rank
# (soil's min_level=5 is greater than bare's min_level=1). Band lookups must be
# correct regardless of the feed order.
MISORDERED_STAGE_ROWS = [
    {"slug": "soil", "name": "Fallow Soil", "blurb": "b", "min_level": 5, "xp_to_complete": 300, "sort_order": 0},
    {"slug": "bare", "name": "Bare Soil", "blurb": "b", "min_level": 1, "xp_to_complete": 200, "sort_order": 1},
    {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10, "xp_to_complete": 500, "sort_order": 2},
    {"slug": "sprout", "name": "Sprout", "blurb": "b", "min_level": 15, "xp_to_complete": 800, "sort_order": 3},
    {"slug": "old", "name": "Old Growth", "blurb": "b", "min_level": 20, "xp_to_complete": None, "sort_order": 4},
]


class TestBandLookupDoesNotDependOnQueryOrder:
    """Regression for a sort_order/min_level divergence: _band_for_level must not
    rely on the query's sort_order to already be ascending by min_level."""

    def test_stage_and_xp_lookups_correct_when_sort_order_disagrees_with_min_level(self):
        with patch("services.growth.table") as t:
            t.return_value.select.return_value = MISORDERED_STAGE_ROWS
            from services.growth import clear_growth_cache, stage_for_level, xp_for_level
            clear_growth_cache()
            try:
                assert stage_for_level(1)["slug"] == "bare"
                assert stage_for_level(4)["slug"] == "bare"
                assert stage_for_level(5)["slug"] == "soil"
                assert xp_for_level(1) == 50
                assert xp_for_level(5) == 60
            finally:
                clear_growth_cache()
