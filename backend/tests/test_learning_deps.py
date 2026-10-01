"""SaplingDeps carries loop state without changing any existing default."""

from agents.deps import SaplingDeps


def test_defaults_are_inert():
    d = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    assert d.learning_loop is False
    assert d.loop_state is None
    assert d.pending_evidence == []


def test_pending_evidence_is_per_instance():
    a = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    b = SaplingDeps(user_id="v", course_id=None, supabase=None, request_id="s")
    a.pending_evidence.append({"node_id": "n"})
    assert b.pending_evidence == []


def test_existing_defaults_unchanged():
    d = SaplingDeps(user_id="u", course_id=None, supabase=None, request_id="r")
    assert d.session_id is None
    assert d.feature == "unknown"
    assert d.share_class_context is True
    assert d.graph_updates == [] and d.mastery_changes == [] and d.retrieval is None
