from fastapi import APIRouter

from db.connection import table
from models import SubmitFeedbackBody, SubmitIssueReportBody

router = APIRouter()


@router.post("/feedback")
def submit_feedback(body: SubmitFeedbackBody):
    table("feedback").insert({
        "user_id": body.user_id,
        "type": body.type,
        "rating": body.rating,
        "selected_options": body.selected_options,
        "comment": body.comment,
        "session_id": body.session_id,
        "topic": body.topic,
    })
    return {"ok": True}


@router.post("/issue-reports")
def submit_issue_report(body: SubmitIssueReportBody):
    table("issue_reports").insert({
        "user_id": body.user_id,
        "topic": body.topic,
        "description": body.description,
        "screenshot_urls": body.screenshot_urls,
    })
    return {"ok": True}
