"""Learning loop: learner model, scheduler, and tutoring policy.

Pure modules (bkt, fsrs, policy, gates, ladder, leak) import nothing from
agents/, pydantic_ai, google, or db/ — enforced by
tests/test_learning_loop_invariants.py. Spec: docs/superpowers/specs/
2026-09-26-learning-loop-design.md
"""
