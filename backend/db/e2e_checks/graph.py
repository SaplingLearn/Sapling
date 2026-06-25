"""E2E journey: graph — courses-with-term, get_graph shape, course color, recommendations.

Mounted at /api/graph (see main.py). Assumes the academics journey ran first and the
e2e user is already enrolled in COURSE_ID's current-term offering.
"""
from db.e2e_staging_http import client, check, COURSE_ID, USER_ID
from db.connection import table  # noqa: F401  (available for future assertions)


def run() -> None:
    # ── 1. List user's courses — assert COURSE_ID present and term label surfaced ──
    r = client.get(f"/api/graph/{USER_ID}/courses")
    courses = r.json().get("courses", []) if r.status_code == 200 else []
    mine = [c for c in courses if c.get("course_id") == COURSE_ID]
    check(
        "GET /api/graph/<u>/courses (term surfaced)",
        r.status_code == 200 and bool(mine) and "term" in (mine[0] if mine else {}),
        f"term={mine[0].get('term') if mine else None}",
    )

    # ── 2. Full graph — response must have nodes, edges, stats keys ──
    r = client.get(f"/api/graph/{USER_ID}")
    body = r.json() if r.status_code == 200 else {}
    check(
        "GET /api/graph/<u> (nodes/edges/stats)",
        r.status_code == 200 and {"nodes", "edges", "stats"} <= set(body.keys()),
        f"keys={list(body.keys())}",
    )

    # ── 3. Update course color — PATCH /<user>/courses/<course>/color ──
    #   Body: UpdateCourseColorBody { color: str }
    r = client.patch(
        f"/api/graph/{USER_ID}/courses/{COURSE_ID}/color",
        json={"color": "#123456"},
    )
    check("PATCH course color", r.status_code == 200, f"got {r.status_code}")

    # ── 4. Recommendations — response wraps list under "recommendations" key ──
    r = client.get(f"/api/graph/{USER_ID}/recommendations")
    check(
        "GET /api/graph/<u>/recommendations",
        r.status_code == 200 and "recommendations" in (r.json() if r.status_code == 200 else {}),
        f"got {r.status_code}",
    )
