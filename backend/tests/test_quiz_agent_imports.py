"""Import smoke test for the quiz agent. Live-Gemini behavior is
covered by the eval set in tests/evals/quiz_generation.py (run via
SAPLING_EVAL_MODE=record/replay)."""


def test_quiz_agent_imports_and_has_tools():
    from agents.quiz import quiz_agent, Quiz

    assert quiz_agent.deps_type.__name__ == "SaplingDeps"
    assert quiz_agent.output_type is Quiz
    # Both graph-read tools should be registered. In pydantic-ai 1.89,
    # the function-tool registry lives on Agent._function_toolset.tools
    # as a dict keyed by tool name. (Agent.toolset is a method on the
    # public surface, not the toolset object — don't reach for it.)
    tool_names = set(quiz_agent._function_toolset.tools.keys())
    assert "read_concepts_for_user_tool" in tool_names
    assert "read_misconceptions_for_course_tool" in tool_names


def test_quiz_question_fields_align_with_route_contract():
    """The route writes these fields back to the quiz row; if you
    rename one, the route refactor in routes/quiz.py needs to follow."""
    from agents.quiz import QuizQuestion

    fields = set(QuizQuestion.model_fields.keys())
    expected = {
        "question",
        "type",
        "difficulty",
        "options",
        "correct_answer",
        "explanation",
        "concept",
    }
    assert fields == expected
