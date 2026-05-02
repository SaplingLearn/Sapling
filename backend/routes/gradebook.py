"""
backend/routes/gradebook.py

User-driven gradebook: categories with weights, graded assignments,
per-course letter-scale override, syllabus-apply.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request

from db.connection import table
from models import (
    CreateCategoryBody,
    BulkUpdateCategoriesBody,
    CreateAssignmentBody,
    UpdateAssignmentBody,
    SetLetterScaleBody,
    SyllabusApplyBody,
)
from services import gradebook_service
from services.auth_guard import require_self

router = APIRouter()


def _user_owns_course(user_id: str, course_id: str) -> bool:
    rows = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
        limit=1,
    )
    return bool(rows)


def _user_owns_category(user_id: str, category_id: str) -> dict | None:
    rows = table("course_categories").select(
        "*",
        filters={"id": f"eq.{category_id}", "user_id": f"eq.{user_id}"},
        limit=1,
    )
    return rows[0] if rows else None
