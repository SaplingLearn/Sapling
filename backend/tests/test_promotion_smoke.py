"""Post-deploy smoke checks for the promotion runner (#516).

`run_checks` takes an injected fetcher, so these tests make no network calls.
"""
import json

from promotion.smoke import CHECKS, Check, format_results, live_commit, run_checks

API = "https://api.example.test"
WEB = "https://example.test"

HEALTH_BODY = json.dumps({"status": "ok", "service": "sapling-backend", "commit": "abc1234"})


def fetcher(routes):
    """Build a fetch(method, url) -> (status, body) from a {(method, url): (status, body)} map."""

    def fetch(method, url):
        return routes.get((method, url), (404, "not found"))

    return fetch


def test_check_passes_on_expected_status_and_body():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,), expect_body='"status":"ok"')
    fetch = fetcher({("GET", f"{API}/api/health"): (200, '{"status":"ok"}')})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True
    assert result.status == 200


def test_check_fails_on_wrong_status():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,))
    fetch = fetcher({("GET", f"{API}/api/health"): (503, "down")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False
    assert "503" in result.detail


def test_check_fails_when_body_marker_missing():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,), expect_body='"status":"ok"')
    fetch = fetcher({("GET", f"{API}/api/health"): (200, '{"status":"degraded"}')})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False
    assert "missing" in result.detail


def test_guarded_route_counts_401_as_mounted():
    """A 401 proves the router is mounted; the pre-promotion failure mode was 404."""
    check = Check(name="analytics", target="api", path="/api/admin/analytics/usage/summary", expect_status=(401, 403))
    fetch = fetcher({("GET", f"{API}/api/admin/analytics/usage/summary"): (401, "")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True


def test_guarded_route_fails_on_404():
    check = Check(name="analytics", target="api", path="/api/admin/analytics/usage/summary", expect_status=(401, 403))
    fetch = fetcher({("GET", f"{API}/api/admin/analytics/usage/summary"): (404, "")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is False


def test_web_target_uses_the_web_base():
    check = Check(name="web root", target="web", path="/", expect_status=(200,))
    fetch = fetcher({("GET", f"{WEB}/"): (200, "<html>")})
    [result] = run_checks(fetch, API, WEB, [check])
    assert result.ok is True


def test_unreachable_host_is_a_failure_not_a_crash():
    def fetch(method, url):
        return None, "connection refused"

    [result] = run_checks(fetch, API, WEB, [Check(name="health", target="api", path="/api/health", expect_status=(200,))])
    assert result.ok is False
    assert result.status is None


def test_default_checks_cover_the_promotion_surface():
    paths = {c.path for c in CHECKS}
    assert "/api/health" in paths
    assert "/api/semesters" in paths
    assert "/api/admin/analytics/usage/summary" in paths
    assert "/api/auth/test-login" in paths
    assert "/" in paths


def test_default_checks_have_no_term_specific_assertions():
    """#515's fall-2026 assertions were promotion-specific and would rot."""
    for check in CHECKS:
        assert "fall-2026" not in check.expect_body
        assert "2026-05-18" not in check.expect_body


def test_test_login_check_is_a_post_expecting_404():
    [check] = [c for c in CHECKS if c.path == "/api/auth/test-login"]
    assert check.method == "POST"
    assert check.expect_status == (404,)


def test_live_commit_reads_health():
    fetch = fetcher({("GET", f"{API}/api/health"): (200, HEALTH_BODY)})
    assert live_commit(fetch, API) == "abc1234"


def test_live_commit_empty_when_unreachable():
    def fetch(method, url):
        return None, ""

    assert live_commit(fetch, API) == ""


def test_live_commit_empty_on_unparseable_body():
    fetch = fetcher({("GET", f"{API}/api/health"): (200, "<html>502</html>")})
    assert live_commit(fetch, API) == ""


def test_format_results_marks_pass_and_fail():
    check = Check(name="health", target="api", path="/api/health", expect_status=(200,))
    fetch = fetcher({("GET", f"{API}/api/health"): (500, "boom")})
    text = format_results(run_checks(fetch, API, WEB, [check]))
    assert "FAIL" in text and "health" in text
