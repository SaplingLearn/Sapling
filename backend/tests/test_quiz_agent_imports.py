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
    assert "read_recent_quiz_attempts_tool" in tool_names


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


class TestPracticalQuestionMix:
    """Quizzes skewed conceptual ("what IS a Markov chain?") when what builds
    competence in a quantitative course is working the problem. The prompt now
    requires a majority of worked problems for quantitative concepts.

    Enforced in the prompt, not the schema: QuizQuestion's own comments record
    that Gemini's constrained decoding hit "too many states for serving" on
    the Lite tier, so a question-kind enum would cost us the cheap models.
    """

    def test_prompt_requires_a_majority_of_worked_problems(self):
        from agents.quiz import _SYSTEM_PROMPT

        assert "PRACTICAL OVER CONCEPTUAL" in _SYSTEM_PROMPT
        assert "ceil(2N/3)" in _SYSTEM_PROMPT
        assert "MOST QUESTIONS MUST BE WORKED PROBLEMS" in _SYSTEM_PROMPT

    def test_prompt_keeps_a_conceptual_remainder(self):
        """Practical-only would be an overcorrection -- the ask was a mix."""
        from agents.quiz import _SYSTEM_PROMPT

        assert "Keep the remainder conceptual" in _SYSTEM_PROMPT

    def test_distractors_must_be_plausible_wrong_results(self):
        from agents.quiz import _SYSTEM_PROMPT

        assert "candidate RESULTS" in _SYSTEM_PROMPT
        assert "Never pad with arbitrary numbers" in _SYSTEM_PROMPT

    def test_non_quantitative_subjects_get_applied_analysis(self):
        from agents.quiz import _SYSTEM_PROMPT

        assert "NON-QUANTITATIVE" in _SYSTEM_PROMPT
        assert "applied analysis over recall" in _SYSTEM_PROMPT

    def test_schema_stays_mcq_only(self):
        """The frontend grades by option lookup; short-answer would be
        unrenderable and ungradable. A 'problem' is still four options."""
        from agents.quiz import QuizQuestion

        anno = QuizQuestion.model_fields["type"].annotation
        assert "multiple_choice" in str(anno)
        opts = QuizQuestion.model_fields["options"]
        assert [m for m in opts.metadata if getattr(m, "min_length", None) == 4]
