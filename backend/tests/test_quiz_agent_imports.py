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
        assert "COUNT THE QUESTIONS THAT POSE NO CONCRETE VALUES" in tail
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


def _q(name: str, kind: str = "worked_problem", correct: str = "a"):
    """A question whose TEXT makes it worked or conceptual.

    `kind` was a schema field until it was measured making Gemini fail
    generation (see the A/B in agents/quiz.py). Classification is read
    off the stem now, so the fixture produces a realistic stem rather
    than setting a flag.
    """
    from agents.quiz import QuizQuestion

    stem = (
        f"{name}: P = [[0.7, 0.3], [0.4, 0.6]] - compute the next state."
        if kind == "worked_problem"
        else f"{name}: what does an absorbing state mean?"
    )
    return QuizQuestion(
        question=stem, type="multiple_choice", difficulty="medium",
        options=["a", "b", "c", "d"], correct_answer=correct,
        explanation="because", concept="Markov Chains",
    )


class TestOverGenerateAndSelect:
    """The ratio is SELECTED from a surplus, not negotiated by retrying.

    Enforcing it with ModelRetry is what broke quiz generation outright:
    every retry re-runs the whole generation, and the route caps a run at
    ORCHESTRATOR_LIMITS (8 model requests / 100k tokens). Measured on the
    real route: a 10-question request took 43s and STILL served 5
    conceptual questions; another ran 361s before dying as a 502. After
    switching to selection the same request is 17.8s / 200.
    """

    def test_asks_for_a_surplus_so_there_is_something_to_select_from(self):
        from agents.quiz import quiz_ask_size

        for wanted in (3, 5, 8):
            assert quiz_ask_size(wanted) > wanted
        # Bounded, and deliberately small: a bigger ask is a likelier flake.
        # Asking flash-lite for 20 produced noticeably more short and
        # malformed returns than asking for 17.
        assert quiz_ask_size(5) == 7
        assert quiz_ask_size(10) == 10

    def test_prefers_worked_problems_and_keeps_one_conceptual(self):
        from agents.quiz import is_worked_problem, select_quiz_questions

        questions = [_q(f"w{i}") for i in range(9)] + [
            _q(f"c{i}", kind="conceptual") for i in range(3)
        ]
        chosen, notes = select_quiz_questions(questions, 10)
        assert len(chosen) == 10
        assert sum(1 for q in chosen if not is_worked_problem(q)) == 1
        assert notes == []

    def test_drops_unanswerable_questions_using_the_surplus(self):
        from agents.quiz import is_worked_problem, select_quiz_questions

        # correct_answer matches no option — the 'vP = [0.25, 0.75]' case.
        broken = _q("broken", correct="zzz-not-an-option")
        questions = [broken] + [_q(f"w{i}") for i in range(11)]
        chosen, notes = select_quiz_questions(questions, 10)
        assert len(chosen) == 10
        assert broken not in chosen
        assert any("unanswerable" in n for n in notes)

    def test_serves_a_full_quiz_over_a_perfect_ratio(self):
        """A quiz one question short is a worse failure than a slightly
        definitional one — so the allowance yields before the count does."""
        from agents.quiz import is_worked_problem, select_quiz_questions

        questions = [_q(f"w{i}") for i in range(6)] + [
            _q(f"c{i}", kind="conceptual") for i in range(6)
        ]
        chosen, notes = select_quiz_questions(questions, 10)
        assert len(chosen) == 10
        assert sum(1 for q in chosen if not is_worked_problem(q)) == 4
        assert any("over the allowance" in n for n in notes)

    def test_reports_a_genuine_shortfall_instead_of_padding(self):
        from agents.quiz import is_worked_problem, select_quiz_questions

        chosen, notes = select_quiz_questions([_q("w1"), _q("w2")], 10)
        assert len(chosen) == 2
        assert any("served 2 of 10" in n for n in notes)

    def test_keeps_the_model_s_ordering(self):
        """Selection groups by kind; without restoring order every quiz would
        front-load the worked problems and park the definition last."""
        from agents.quiz import is_worked_problem, select_quiz_questions

        questions = [
            _q("w1"), _q("c1", kind="conceptual"), _q("w2"), _q("w3"),
            _q("w4"), _q("w5"),
        ]
        chosen, _ = select_quiz_questions(questions, 5)
        assert [q.question.split(":")[0] for q in chosen] == [
            "w1", "c1", "w2", "w3", "w4",
        ]

    def test_reserves_the_conceptual_slot_rather_than_merely_allowing_it(self):
        """"9 worked problems AND one conceptual question" — so with plenty of
        worked problems to fill the quiz outright, the conceptual one is still
        included. Taking worked-only would drop the question that checks
        whether the student knows what they are computing."""
        from agents.quiz import is_worked_problem, select_quiz_questions

        questions = [_q(f"w{i}") for i in range(12)] + [
            _q("c1", kind="conceptual")
        ]
        chosen, notes = select_quiz_questions(questions, 10)
        assert len(chosen) == 10
        assert sum(1 for q in chosen if not is_worked_problem(q)) == 1
        assert notes == []

    def test_no_conceptual_available_is_not_an_error(self):
        from agents.quiz import is_worked_problem, select_quiz_questions

        chosen, notes = select_quiz_questions([_q(f"w{i}") for i in range(11)], 10)
        assert len(chosen) == 10
        assert all(is_worked_problem(q) for q in chosen)
        assert notes == []

    def test_allowance_is_one_up_to_ten_and_two_through_fifteen(self):
        from agents.quiz import conceptual_allowance

        assert [conceptual_allowance(n) for n in (3, 5, 10)] == [1, 1, 1]
        assert [conceptual_allowance(n) for n in (11, 15)] == [2, 2]


class TestSelectionValidator:
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

    def test_trims_the_surplus_to_the_requested_count(self):
        from agents.quiz import Quiz, _select_requested_quiz

        quiz = Quiz(questions=[_q(f"w{i}") for i in range(10)])
        assert len(_select_requested_quiz(self._ctx(10), quiz).questions) == 10

    def test_a_shortfall_is_served_short_never_raised(self):
        """The validator must never be the reason a student gets no quiz.

        Raising here is precisely what produced the reported 500s:
        flash-lite intermittently returns almost nothing (one sampled run:
        a single usable question), re-asking produced the same, and the run
        died as UnexpectedModelBehavior -> 502. One request in five.
        """
        from agents.quiz import Quiz, _select_requested_quiz

        quiz = Quiz(questions=[_q("w1"), _q("w2")])
        out = _select_requested_quiz(self._ctx(10), quiz)
        assert len(out.questions) == 2

    def test_the_validator_never_raises_on_any_shape(self):
        """Belt and braces: no input shape may turn into an exception."""
        from agents.quiz import Quiz, _select_requested_quiz

        shapes = [
            [_q("w1")],
            [_q("c1", kind="conceptual")],
            [_q("broken", correct="zzz")],
            [_q(f"w{i}") for i in range(10)],
            [_q(f"c{i}", kind="conceptual") for i in range(10)],
        ]
        for questions in shapes:
            out = _select_requested_quiz(self._ctx(10), Quiz(questions=questions))
            assert len(out.questions) >= 1

    def test_an_imperfect_ratio_never_retries(self):
        """This is the regression that caused the 502s: a ratio miss used to
        re-run the whole generation, twice."""
        from agents.quiz import Quiz, _select_requested_quiz

        quiz = Quiz(questions=(
            [_q(f"w{i}") for i in range(4)]
            + [_q(f"c{i}", kind="conceptual") for i in range(6)]
        ))
        out = _select_requested_quiz(self._ctx(10), quiz)  # must not raise
        assert len(out.questions) == 10

    def test_no_requested_count_is_a_no_op(self):
        from agents.quiz import Quiz, _select_requested_quiz

        quiz = Quiz(questions=[_q("w1")])
        assert _select_requested_quiz(self._ctx(None), quiz) is quiz

    def test_function_mode_fixture_is_left_alone(self):
        """The E2E seam's fixed 3-question quiz answers a request for 2 on
        purpose; trimming it would break quiz.spec.ts and the mastery math."""
        from unittest.mock import patch
        from agents.quiz import Quiz, _select_requested_quiz

        quiz = Quiz(questions=[_q("w1"), _q("w2"), _q("w3")])
        with patch("agents.quiz.model_mode", return_value="function"):
            out = _select_requested_quiz(self._ctx(2), quiz)
        assert out is quiz and len(out.questions) == 3

    def test_budget_is_read_from_the_run_context(self):
        from agents.quiz import _OUTPUT_RETRIES, quiz_agent

        assert quiz_agent._max_output_retries == _OUTPUT_RETRIES
