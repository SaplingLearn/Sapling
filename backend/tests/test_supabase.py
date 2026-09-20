"""
test_supabase.py — Run from backend/ to verify Supabase connectivity.

Usage:
    cd backend
    python test_supabase.py
"""

import os
import sys

# Allow running from anywhere inside the project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
INFO = "\033[94m→\033[0m"


def check(label: str, ok: bool, detail: str = ""):
    symbol = PASS if ok else FAIL
    msg = f"  {symbol}  {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg)
    return ok


def main():
    print("\n\033[1mSapling — Supabase connection test\033[0m\n")
    all_ok = True

    # ── 1. Env vars ──────────────────────────────────────────────────────────
    print(f"{INFO} Checking environment variables …")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")

    url_ok = bool(supabase_url and "supabase.co" in supabase_url and "your-project" not in supabase_url)
    key_ok = bool(supabase_key and len(supabase_key) > 20 and "your-service" not in supabase_key)

    all_ok &= check("SUPABASE_URL set", url_ok, supabase_url[:40] + "…" if url_ok else "not set or still placeholder")
    all_ok &= check("SUPABASE_SERVICE_KEY set", key_ok, "looks valid" if key_ok else "not set or still placeholder")

    if not (url_ok and key_ok):
        print(f"\n  \033[93m⚠\033[0m  Set SUPABASE_URL and SUPABASE_SERVICE_KEY in backend/.env")
        print(f"  {INFO}  Get them from: Supabase Dashboard → your project → Settings → API\n")
        sys.exit(1)

    # ── 2. HTTP connectivity ──────────────────────────────────────────────────
    print(f"\n{INFO} Testing HTTP connectivity …")
    import httpx
    try:
        r = httpx.get(f"{supabase_url}/rest/v1/", headers={
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        }, timeout=10)
        http_ok = r.status_code < 500
        all_ok &= check("HTTP connection", http_ok, f"status {r.status_code}")
    except Exception as e:
        all_ok &= check("HTTP connection", False, str(e))
        print(f"\n  \033[93m⚠\033[0m  Cannot reach Supabase. Check your SUPABASE_URL.\n")
        sys.exit(1)

    # ── 3. Table access ───────────────────────────────────────────────────────
    print(f"\n{INFO} Checking table access …")
    from db.connection import table

    TABLES = ["users", "graph_nodes", "graph_edges", "courses", "sessions", "messages",
              "quiz_attempts", "quiz_context", "assignments", "oauth_tokens",
              "rooms", "room_members", "room_activity", "room_summaries"]

    for tname in TABLES:
        try:
            rows = table(tname).select("*", limit=1)
            all_ok &= check(f"table: {tname}", True, f"{len(rows)} row(s) returned")
        except Exception as e:
            all_ok &= check(f"table: {tname}", False, str(e))

    # ── 4. Summary ────────────────────────────────────────────────────────────
    print()
    if all_ok:
        print(f"  \033[92m✓ All checks passed — Supabase is connected and all tables are accessible.\033[0m")
    else:
        print(f"  \033[91m✗ Some checks failed. Review the output above.\033[0m")
        print(f"  {INFO}  If tables are missing, run: python db/seed.py  (after creating schema in Supabase)")
    print()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()


from unittest.mock import MagicMock, patch
from db.connection import table


class TestSelectWithCount:
    def test_returns_rows_and_total_when_count_exact(self):
        fake = MagicMock()
        fake.json.return_value = [{"id": "1"}]
        fake.headers = {"content-range": "0-0/42"}  # httpx lowercases response headers
        fake.raise_for_status = MagicMock()

        with patch("db.connection._client") as c:
            c.get.return_value = fake
            rows, total = table("users").select_with_count(
                columns="id", limit=1, offset=0
            )

        assert rows == [{"id": "1"}]
        assert total == 42

    def test_total_zero_when_header_missing(self):
        fake = MagicMock()
        fake.json.return_value = []
        fake.headers = {}
        fake.raise_for_status = MagicMock()

        with patch("db.connection._client") as c:
            c.get.return_value = fake
            rows, total = table("users").select_with_count(columns="id")

        assert rows == []
        assert total == 0


class TestPageAll:
    """`page_all` is the one paging loop three XP readers used to hand-roll.

    All three had the same job — read EVERY matching row past PostgREST's
    `max_rows` cap, which truncates with a 206 (a 2xx, so nothing raises) —
    and all three had the same bug, which is why they are one function now.
    """

    def _handle(self, pages):
        """Stub select_with_count to answer `pages` in order.

        Each page is `(rows, total)`, so a test can state a total that
        disagrees with reality — which is the whole point of the first test
        below.
        """
        handle = MagicMock()
        handle.select_with_count.side_effect = list(pages)
        return handle

    def test_a_full_page_keeps_paging_even_when_the_total_reads_zero(self):
        """THE regression (PR #589 review E2).

        `select_with_count` returns `total = 0` whenever the Content-Range
        header is missing or unparseable — a PostgREST version bump, a proxy
        that strips the header, a `Prefer: count=exact` that got dropped.
        A `len(seen) >= total` guard is then satisfied on the FIRST iteration
        even though the page came back completely full, so the loop that
        exists to defeat silent truncation performs the truncation itself.

        A full page is never evidence of the end — only a SHORT page is.
        """
        from db.connection import page_all

        full = [{"amount": 1} for _ in range(3)]
        short = [{"amount": 2}]
        handle = self._handle([(full, 0), (short, 0)])

        rows = list(page_all(handle, "amount", order="id.asc", page=3))

        assert len(rows) == 4, (
            "an unparseable total truncated the read to page one — the exact "
            "silent-truncation this loop exists to prevent"
        )
        assert handle.select_with_count.call_count == 2

    def test_a_short_page_ends_the_read(self):
        from db.connection import page_all

        handle = self._handle([([{"a": 1}, {"a": 2}], 2)])
        rows = list(page_all(handle, "a", order="id.asc", page=3))

        assert rows == [{"a": 1}, {"a": 2}]
        assert handle.select_with_count.call_count == 1

    def test_an_exact_total_still_stops_a_page_early(self):
        """A trustworthy total saves the extra round trip that proves the end:
        a full page that already accounts for every row needs no successor."""
        from db.connection import page_all

        full = [{"a": i} for i in range(3)]
        handle = self._handle([(full, 3)])
        rows = list(page_all(handle, "a", order="id.asc", page=3))

        assert len(rows) == 3
        assert handle.select_with_count.call_count == 1

    def test_an_empty_first_page_ends_the_read(self):
        from db.connection import page_all

        handle = self._handle([([], 0)])
        assert list(page_all(handle, "a", order="id.asc", page=3)) == []
        assert handle.select_with_count.call_count == 1

    def test_it_advances_the_offset_and_forwards_order_and_filters(self):
        """Offset paging without a stable sort can return rows in a different
        order across pages, skipping or duplicating across the boundary — so
        `order` is required and must reach PostgREST unchanged."""
        from db.connection import page_all

        full = [{"a": i} for i in range(3)]
        handle = self._handle([(full, 0), ([], 0)])
        list(page_all(
            handle, "amount",
            filters={"user_id": "eq.u1"}, order="created_at.asc,id.asc", page=3,
        ))

        first, second = handle.select_with_count.call_args_list
        assert first.kwargs["offset"] == 0
        assert second.kwargs["offset"] == 3
        assert first.kwargs["limit"] == 3
        assert first.kwargs["order"] == "created_at.asc,id.asc"
        assert first.kwargs["filters"] == {"user_id": "eq.u1"}
        assert first.args[0] == "amount"

    def test_it_refuses_a_page_size_above_postgrest_max_rows(self):
        """Above `max_rows` every page comes back short by construction, so
        the short-page terminator would end the read after `max_rows` rows and
        call it complete. Fail loudly instead of truncating quietly."""
        import pytest

        from db.connection import MAX_ROWS, page_all

        with pytest.raises(ValueError):
            list(page_all(self._handle([]), "a", order="id.asc", page=MAX_ROWS + 1))
