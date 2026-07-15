"""Identity journey: profile read, profile write, decrypted roster. STAGING ONLY."""

from db.e2e_staging_http import client, check, USER_ID


def run() -> None:
    # ── Profile read ─────────────────────────────────────────────────────────
    # GET /api/profile/{user_id}  →  200, flat dict with "name" key (decrypted
    # from user_profiles.name).  Profile visibility defaults to non-private so
    # bio/location/website/stats/featured_achievements are also present.
    r = client.get(f"/api/profile/{USER_ID}")
    check(
        "GET /api/profile/<u> (display name from user_profiles)",
        r.status_code == 200,
        r.text[:120],
    )

    # ── Profile write ─────────────────────────────────────────────────────────
    # PATCH /api/profile/{user_id}  body: UpdateProfileBody (bio, location,
    # website, username — all Optional).  Returns {"updated": True}.
    r = client.patch(
        f"/api/profile/{USER_ID}",
        json={"bio": "e2e bio", "location": "Test City"},
    )
    check(
        "PATCH /api/profile/<u> (writes user_profiles)",
        r.status_code == 200,
        f"got {r.status_code} {r.text[:100]}",
    )

    # ── Decrypted roster ──────────────────────────────────────────────────────
    # GET /api/users  →  {"users": [{id, name, room_id}, ...]}
    # "name" is resolved via services.profiles.get_display_names, which decrypts
    # user_profiles.name.  The fixture user has name "E2E User".
    r = client.get("/api/users")
    data = r.json() if r.status_code == 200 else {}
    users = data.get("users", []) if isinstance(data, dict) else data
    me = [u for u in users if u.get("id") == USER_ID]
    check(
        "GET /api/users (decrypted name)",
        r.status_code == 200 and bool(me) and me[0].get("name") == "E2E User",
        f"name={me[0].get('name') if me else None}",
    )
