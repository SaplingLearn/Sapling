"""Reason-before-submit on free / teachback checks (W2.3 / plan S).

Optional student prose sealed into ``sessions.loop_state`` under the step's
``reasoning_encrypted`` key (``encryption.NESTED_CIPHERTEXTS``). Diagnostic
only: never graded, never evidence, never a mastery input. The grader still
sees answer + rubric only (``reason`` remains the mc_reason one-sentence field).

W2.4b opens the sealed field under the session bind for the low-trust
next-probe hint only — never as evidence / never into mastery.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite

from services.encryption import decrypt_if_present, encrypt_if_present, nested_bind

#: Object key on a check step (and the NESTED_CIPHERTEXTS path name).
KEY = "reasoning_encrypted"

#: Formats that may carry the optional field; mc_reason keeps graded ``reason``.
_ALLOWED = frozenset({"free", "teachback"})


def _binding(session_id: str):
    """Session-bound AAD for the nested reasoning cell (finding M13)."""
    return nested_bind("sessions", "loop_state", KEY, session_id)


def normalize(format: str | None, reasoning: str | None) -> str:
    """Strip for free/teachback; empty for every other format (ignore / drop)."""
    if format not in _ALLOWED:
        return ""
    return (reasoning or "").strip()


def seal(session_id: str, plaintext: str) -> str | None:
    """AES-GCM seal bound to the session; None when plaintext is empty."""
    text = (plaintext or "").strip()
    if not text:
        return None
    return encrypt_if_present(text, bind=_binding(session_id))


def open(session_id: str, sealed: str | None) -> str | None:
    """Open sealed reasoning under the session bind; None on miss / wrong bind."""
    if not sealed or not isinstance(sealed, str):
        return None
    return decrypt_if_present(sealed, bind=_binding(session_id))


def latest_plaintext(state: Mapping | None, session_id: str | None) -> str | None:
    """Most recently graded step's opened reasoning, or None.

    Scans ``state["steps"]`` for ``reasoning_encrypted``; prefers the highest
    finite ``graded_at`` (then ``question_hash``). Wrong-session ciphertext
    opens as None. Never writes; never touches mastery.
    """
    if not session_id or not isinstance(state, Mapping):
        return None
    steps = state.get("steps")
    if not isinstance(steps, dict) or not steps:
        return None
    best_key: tuple[float, str] | None = None
    best_sealed: str | None = None
    for qh, entry in steps.items():
        if not isinstance(entry, dict):
            continue
        sealed = entry.get(KEY)
        if not isinstance(sealed, str) or not sealed:
            continue
        at = entry.get("graded_at")
        if type(at) not in (int, float) or not isfinite(at):
            at = 0.0
        key = (float(at), str(qh))
        if best_key is None or key > best_key:
            best_key = key
            best_sealed = sealed
    return open(session_id, best_sealed) if best_sealed is not None else None


def stash_on_step(entry: dict, session_id: str, *, format: str | None, reasoning: str | None) -> None:
    """Write the sealed field onto the step, or leave the entry unchanged."""
    sealed = seal(session_id, normalize(format, reasoning))
    if sealed is not None:
        entry[KEY] = sealed
