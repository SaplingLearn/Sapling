"""backend/models/gradescope.py

Request/response schemas matching the contract already defined in
frontend/src/lib/api.ts (GradescopeStatus, GradescopeConnectInput,
GradescopeCourse, GradescopeLink, GradescopeSyncResult).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

GradescopeAuthMode = Literal["password", "cookies"]


class GradescopeCredentialsIn(BaseModel):
    """Body for POST /api/gradescope/credentials.

    Matches frontend's GradescopeConnectInput union:
      - auth_mode='password' -> email + password required
      - auth_mode='cookies'  -> gradescope_session required, signed_token optional
    """

    user_id: str
    auth_mode: GradescopeAuthMode
    email: Optional[str] = None
    password: Optional[str] = None
    gradescope_session: Optional[str] = None
    signed_token: Optional[str] = None

    def validate_mode(self) -> None:
        if self.auth_mode == "password" and not (self.email and self.password):
            raise ValueError("email and password are required for auth_mode='password'")
        if self.auth_mode == "cookies" and not self.gradescope_session:
            raise ValueError("gradescope_session is required for auth_mode='cookies'")


class GradescopeStatus(BaseModel):
    """Response for GET /api/gradescope/status. Matches frontend's
    GradescopeStatus interface exactly."""

    has_credentials: bool
    auth_mode: Optional[GradescopeAuthMode] = None
    last_synced_at: Optional[datetime] = None
    credentials_updated_at: Optional[datetime] = None


class GradescopeCourse(BaseModel):
    """A course as returned by Gradescope itself (not yet linked to a
    Sapling course). Matches frontend's GradescopeCourse interface."""

    id: str
    name: str
    full_name: str
    semester: str
    year: str
    num_assignments: str


class GradescopeLink(BaseModel):
    """A saved Sapling<->Gradescope course mapping. Matches frontend's
    GradescopeLink interface."""

    id: str
    sapling_course_id: str
    gradescope_course_id: str
    last_synced_at: Optional[datetime] = None


class GradescopeLinkIn(BaseModel):
    """Body for POST /api/gradescope/link."""

    user_id: str
    sapling_course_id: str
    gradescope_course_id: str


class GradescopeSyncResult(BaseModel):
    """Response for POST /api/gradescope/sync/{sapling_course_id}. Matches
    frontend's GradescopeSyncResult interface exactly (note: 'failed', not
    'errors' — per-assignment failures are counted, not itemized, to match
    this shape)."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0