"""Admin account tools: the per-user in-process operation guard."""
import threading

import pytest

from services import account_ops_lock as lk


def test_second_op_on_the_same_user_is_rejected_not_queued():
    with lk.account_op("u1"):
        assert lk.is_busy("u1")
        with pytest.raises(lk.AccountBusy) as exc:
            with lk.account_op("u1"):
                pytest.fail("the body of a rejected op must not run")
        assert exc.value.user_id == "u1"
    assert not lk.is_busy("u1")


def test_different_users_do_not_block_each_other():
    with lk.account_op("u1"), lk.account_op("u2"):
        assert lk.is_busy("u1") and lk.is_busy("u2")


def test_slot_is_released_when_the_body_raises():
    with pytest.raises(RuntimeError):
        with lk.account_op("u1"):
            raise RuntimeError("boom")
    with lk.account_op("u1"):  # free again
        pass


def test_rejection_does_not_release_the_holders_slot():
    with lk.account_op("u1"):
        with pytest.raises(lk.AccountBusy):
            with lk.account_op("u1"):
                pass
        assert lk.is_busy("u1")  # the first op still holds it


def test_exactly_one_thread_wins_a_race():
    n = 16
    barrier = threading.Barrier(n)
    release = threading.Event()
    results: list[str] = []
    guard = threading.Lock()

    def worker():
        barrier.wait()
        try:
            with lk.account_op("racy"):
                with guard:
                    results.append("won")
                release.wait(5)
        except lk.AccountBusy:
            with guard:
                results.append("busy")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    # Wait until every loser has reported, then let the winner finish.
    for _ in range(500):
        with guard:
            if results.count("busy") == n - 1:
                break
        threading.Event().wait(0.01)
    release.set()
    for t in threads:
        t.join(5)

    assert results.count("won") == 1
    assert results.count("busy") == n - 1
    assert not lk.is_busy("racy")
