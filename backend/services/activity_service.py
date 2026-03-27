import uuid
from db.connection import table


def log_room_activity(
    user_id: str,
    activity_type: str,
    concept_name: str | None = None,
    detail: str = "",
    room_id: str | None = None,
) -> None:
    """Insert an activity row. If room_id is given, logs only to that room;
    otherwise logs to every room the user belongs to."""
    if room_id:
        room_ids = [room_id]
    else:
        room_rows = table("room_members").select("room_id", filters={"user_id": f"eq.{user_id}"})
        room_ids = [row["room_id"] for row in room_rows]

    for rid in room_ids:
        table("room_activity").insert([{
            "id": str(uuid.uuid4()),
            "room_id": rid,
            "user_id": user_id,
            "activity_type": activity_type,
            "concept_name": concept_name,
            "detail": detail,
        }])
