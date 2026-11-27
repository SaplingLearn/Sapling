"""W7 richer kit grading — order-insensitive / calculate value|unit."""

from services.quiz.grading import grade_written
from services.quiz.kit_grade import kit_answers_match


def test_sort_ignores_item_order_inside_bucket():
    q = {
        "type": "short_answer",
        "correct_answer": "Prokaryote=ecoli,strep;Eukaryote=yeast",
        "interaction": {"kind": "sort", "buckets": ["Prokaryote", "Eukaryote"], "items": []},
    }
    assert kit_answers_match(q, "Prokaryote=strep,ecoli;Eukaryote=yeast") is True
    assert grade_written(q, "Prokaryote=strep,ecoli;Eukaryote=yeast") is True
    assert grade_written(q, "Prokaryote=ecoli;Eukaryote=yeast") is False


def test_calculate_grades_value_unit_ignoring_steps():
    q = {
        "type": "short_answer",
        "correct_answer": "9.8|m/s^2",
        "interaction": {"kind": "calculate"},
    }
    assert grade_written(q, "9.8|m/s^2|I used g from the lecture") is True
    assert grade_written(q, "9.8|m/s") is False


def test_connect_map_ignores_edge_order():
    q = {
        "type": "short_answer",
        "correct_answer": "a=b;b=c",
        "interaction": {"kind": "connect", "mode": "map", "nodes": []},
    }
    assert grade_written(q, "b=c;a=b") is True
