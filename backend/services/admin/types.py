"""
backend/services/admin/types.py

Shared types for the admin package (#118).
"""
from __future__ import annotations

from typing import Callable

#: ``routes/auth.py::_waitlist_entries(email, columns)`` — every case twin of an
#: address on the waitlist. The admin routes pass it in, since a domain package
#: may not import ``routes.*``.
WaitlistEntries = Callable[[str, str], list[dict]]
