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
        # Not on the wire — the route never emits it. It exists so the
        # practical/conceptual ratio can be counted in the output
        # validator instead of merely asked for in the prompt.
        "kind",
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

    def test_prompt_allows_at_most_one_or_two_conceptual_questions(self):
        from agents.quiz import _SYSTEM_PROMPT

        assert "PRACTICAL OVER CONCEPTUAL" in _SYSTEM_PROMPT
        assert "NEARLY EVERY QUESTION MUST BE A WORKED PROBLEM" in _SYSTEM_PROMPT
        # The ratio the user asked for, stated as the concrete counts the
        # UI can actually request (QuizPanel offers 5 / 10 / 15).
        assert "4 of 5, 9 of 10, 13 of 15" in _SYSTEM_PROMPT
        assert "AT MOST ONE question may be purely conceptual" in _SYSTEM_PROMPT

    def test_prompt_keeps_a_conceptual_remainder(self):
        """Practical-only would be an overcorrection -- the ask was a mix."""
        from agents.quiz import _SYSTEM_PROMPT

        assert "Spend the one (or two) conceptual slots well" in _SYSTEM_PROMPT

    def test_the_ratio_is_restated_in_the_final_check(self):
        """Placement finding from the 2026-08-11 spec: a rule stated once
        mid-prompt loses. Both rules claim the first and last slots."""
        from agents.quiz import _SYSTEM_PROMPT

        head, _, tail = _SYSTEM_PROMPT.partition("FINAL CHECK")
        assert tail, "FINAL CHECK block went missing"
        assert "COUNT THE QUESTIONS YOU MARKED kind='conceptual'" in tail
        assert "COUNT YOUR QUESTIONS" in tail
        assert "PRACTICAL OVER CONCEPTUAL" in head

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


class TestRequestedCountIsExact:
    """`num_questions` was prompt-only and the model under-delivered: asked
    for 10 on a real concept, one live run returned 6 and the route served
    all 6 without a word. A short list is a valid Quiz, so nothing caught it.
    """

    def _quiz(self, n: int, kind: str = "worked_problem"):
        from agents.quiz import Quiz, QuizQuestion

        return Quiz(questions=[
            QuizQuestion(
                question=f"q{i}", type="multiple_choice", difficulty="medium",
                options=["a", "b", "c", "d"], correct_answer="a",
                explanation="because", concept="Markov Chains", kind=kind,
            )
            for i in range(n)
        ])

    def _ctx(self, wanted, *, retry=0):
        from agents.deps import SaplingDeps
        from agents.quiz import _OUTPUT_RETRIES

        class _Ctx:
            deps = SaplingDeps(
                user_id="u1", course_id="c1", supabase=None,
                request_id="r1", num_questions=wanted,
            )
        _Ctx.retry = retry
        _Ctx.max_retries = _OUTPUT_RETRIES
        return _Ctx()

    def test_questions_list_has_no_upper_bound(self):
        """A *bounded* array is what pushed flash-lite over 'too many states
        for serving' at 15 (verified 400). The floor stays."""
        from agents.quiz import Quiz

        meta = Quiz.model_fields["questions"].metadata
        assert not [m for m in meta if getattr(m, "max_length", None) is not None]
        assert [m for m in meta if getattr(m, "min_length", None) == 1]

    def test_short_output_is_retried_with_the_shortfall(self):
        from pydantic_ai import ModelRetry
        from agents.quiz import _enforce_requested_count
        import pytest

        with pytest.raises(ModelRetry) as exc:
            _enforce_requested_count(self._ctx(10), self._quiz(6))
        msg = str(exc.value)
        assert "6 questions" in msg and "10 were" in msg
        assert "add 4 more" in msg

    def test_long_output_is_trimmed_not_retried(self):
        from agents.quiz import _enforce_requested_count

        out = _enforce_requested_count(self._ctx(5), self._quiz(8))
        assert len(out.questions) == 5

    def test_exact_output_passes_through(self):
        from agents.quiz import _enforce_requested_count

        quiz = self._quiz(10)
        assert _enforce_requested_count(self._ctx(10), quiz) is quiz

    def test_no_requested_count_is_a_no_op(self):
        """Non-quiz callers and eval harnesses leave num_questions unset."""
        from agents.quiz import _enforce_requested_count

        quiz = self._quiz(3)
        assert _enforce_requested_count(self._ctx(None), quiz) is quiz
        assert _enforce_requested_count(self._ctx(0), quiz) is quiz

    def test_too_many_conceptual_questions_is_retried(self):
        """The ratio is counted, not requested. Prompt-only enforcement was
        measured at 7 worked problems of 10 against a bar of 9, twice."""
        from pydantic_ai import ModelRetry
        from agents.quiz import Quiz, _enforce_requested_count
        import pytest

        mixed = Quiz(questions=(
            self._quiz(7, kind="worked_problem").questions
            + self._quiz(3, kind="conceptual").questions
        ))
        with pytest.raises(ModelRetry) as exc:
            _enforce_requested_count(self._ctx(10), mixed)
        msg = str(exc.value)
        assert "3 of your 10" in msg
        # Names the questions to rewrite — the ones over allowance, not all.
        assert "question(s) 9, 10" in msg

    def test_ratio_at_the_allowance_passes(self):
        from agents.quiz import Quiz, _enforce_requested_count

        ok = Quiz(questions=(
            self._quiz(9, kind="worked_problem").questions
            + self._quiz(1, kind="conceptual").questions
        ))
        assert _enforce_requested_count(self._ctx(10), ok) is ok

    def test_allowance_is_one_up_to_ten_and_two_through_fifteen(self):
        from agents.quiz import conceptual_allowance

        assert [conceptual_allowance(n) for n in (3, 5, 10)] == [1, 1, 1]
        assert [conceptual_allowance(n) for n in (11, 15)] == [2, 2]

    def test_unanswerable_question_is_retried_not_silently_dropped(self):
        """A correct_answer absent from its own options used to cost the
        student a question: the route dropped it and served N-1. The model
        gets a chance to fix it first."""
        from pydantic_ai import ModelRetry
        from agents.quiz import Quiz, QuizQuestion, _enforce_requested_count
        import pytest

        broken = QuizQuestion(
            question="vP?", type="multiple_choice", difficulty="medium",
            options=["vP = [0.55, 0.45]", "vP = [0.45, 0.55]",
                     "vP = [0.7, 0.3]", "vP = [0.6, 0.4]"],
            correct_answer="vP = [0.25, 0.75]",  # matches none of them
            explanation="...", concept="Markov Chains", kind="worked_problem",
        )
        quiz = Quiz(questions=[*self._quiz(2).questions, broken])
        with pytest.raises(ModelRetry) as exc:
            _enforce_requested_count(self._ctx(3), quiz)
        assert "Question(s) 3" in str(exc.value)

    def test_retry_message_scales_the_conceptual_allowance(self):
        from pydantic_ai import ModelRetry
        from agents.quiz import _enforce_requested_count
        import pytest

        with pytest.raises(ModelRetry) as small:
            _enforce_requested_count(self._ctx(10), self._quiz(2))
        assert "at most 1 conceptual" in str(small.value)
        with pytest.raises(ModelRetry) as large:
            _enforce_requested_count(self._ctx(15), self._quiz(2))
        assert "at most 2 conceptual" in str(large.value)


class TestGatesDegradeRatherThanFailTheRun:
    """A quality gate that can 502 is worse than the flaw it guards.

    Measured: a 15-question run tripped gate after gate and exhausted the
    retry budget, raising UnexpectedModelBehavior — the student got an
    error page instead of a quiz with two definitions in it. On the final
    attempt every gate accepts what it has and logs the shortfall.
    """

    def _ctx_final(self, wanted):
        return TestRequestedCountIsExact()._ctx(
            wanted, retry=__import__(
                "agents.quiz", fromlist=["_OUTPUT_RETRIES"]
            )._OUTPUT_RETRIES
        )

    def _mk(self, n, kind="worked_problem", **over):
        return TestRequestedCountIsExact()._quiz(n, kind=kind)

    def test_short_quiz_is_served_on_the_final_attempt(self):
        from agents.quiz import _enforce_requested_count

        out = _enforce_requested_count(self._ctx_final(10), self._mk(6))
        assert len(out.questions) == 6

    def test_over_allowance_ratio_is_served_on_the_final_attempt(self):
        from agents.quiz import Quiz, _enforce_requested_count

        quiz = Quiz(questions=(
            self._mk(5).questions + self._mk(5, kind="conceptual").questions
        ))
        out = _enforce_requested_count(self._ctx_final(10), quiz)
        assert len(out.questions) == 10

    def test_unanswerable_question_is_left_for_the_route_to_drop(self):
        from agents.quiz import Quiz, QuizQuestion, _enforce_requested_count
        from routes.quiz import _agent_question_to_wire

        broken = QuizQuestion(
            question="vP?", type="multiple_choice", difficulty="medium",
            options=["0.55", "0.45", "0.7", "0.6"],
            correct_answer="0.25", explanation="...",
            concept="Markov Chains", kind="worked_problem",
        )
        quiz = Quiz(questions=[*self._mk(2).questions, broken])
        out = _enforce_requested_count(self._ctx_final(3), quiz)
        assert len(out.questions) == 3
        # The net still catches it downstream rather than mis-marking.
        assert _agent_question_to_wire(out.questions[2], qid=3) is None

    def test_function_mode_fixture_is_left_alone(self):
        """The E2E seam's fixed 3-question quiz answers a request for 2 on
        purpose (E2E_QUIZ_CORRECT_LABELS, quiz.spec.ts clicks, mastery
        arithmetic all depend on the 3). Trimming it would break the lane."""
        from unittest.mock import patch
        from agents.quiz import _enforce_requested_count

        quiz = self._mk(3)
        with patch("agents.quiz.model_mode", return_value="function"):
            out = _enforce_requested_count(
                TestRequestedCountIsExact()._ctx(2), quiz
            )
        assert out is quiz and len(out.questions) == 3

    def test_budget_is_read_from_the_run_context(self):
        """The gates must not hardcode a second copy of the retry budget."""
        from agents.quiz import _OUTPUT_RETRIES, quiz_agent

        assert quiz_agent._max_output_retries == _OUTPUT_RETRIES
