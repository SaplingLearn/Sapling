"""PKG-04 post-hoc (owner decision A38, low-severity 3): the ciphertext oracle
and CLAUDE.md's encryption list cover check_items' encrypted columns, so "an
item's prompt and answers are never plaintext at rest" is something the E2E
lane can fail on, not only a claim in services/check_item_service.py."""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]

# services/check_item_service._build_row: every column written through
# encrypt_if_present / encrypt_json (the A22 set, plus final_answer from A34).
ENCRYPTED = (
    "prompt",
    "reference_answer",
    "final_answer",
    "rubric_json",
    "common_wrong_json",
    "options_json",
    "correct_option",
    "canonical_answer",
)


def test_the_ciphertext_oracle_covers_every_encrypted_check_items_column():
    from e2e_oracles.gather import _CIPHERTEXT_MANIFEST

    for column in ENCRYPTED:
        assert ("check_items", "id", column) in _CIPHERTEXT_MANIFEST, column


def test_the_list_matches_what_the_service_encrypts():
    src = (REPO / "backend" / "services" / "check_item_service.py").read_text()
    body = src.split("def _build_row(", 1)[1].split("\ndef ", 1)[0]
    direct = set(re.findall(r'"(\w+)": encrypt_(?:if_present|json)\(', body))
    # options_json / correct_option are encrypted into locals first (mc_reason only)
    assert re.search(r"options = encrypt_json\(", body)
    assert re.search(r"correct_option = encrypt_if_present\(", body)
    assert direct | {"options_json", "correct_option"} == set(ENCRYPTED)


def test_claude_md_lists_them():
    text = (REPO / "CLAUDE.md").read_text()
    (bullet,) = [ln for ln in text.splitlines() if ln.startswith("- Column-level encryption")]
    # written as the file's other entries are: `check_items.prompt`/`reference_answer`/...
    segment = bullet[bullet.index("`check_items.") :].split(" (", 1)[0]
    listed = set(re.findall(r"`(?:check_items\.)?(\w+)`", segment))
    assert set(ENCRYPTED) <= listed, set(ENCRYPTED) - listed
