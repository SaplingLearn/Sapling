"""storage_service.upload_issue_screenshot: an unreachable or refusing Storage
is a clean 502 with generic text, never a raw 500 or Supabase's own body."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException

from services import account_purge, storage_service


def _client(put: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=MagicMock(put=put))
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _upload() -> str:
    return asyncio.run(storage_service.upload_issue_screenshot("user_1", b"png", "image/png"))


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")])
def test_a_transport_error_is_a_502_not_a_500(error):
    put = AsyncMock(side_effect=error)
    with patch("services.storage_service.httpx.AsyncClient", return_value=_client(put)):
        with pytest.raises(HTTPException) as exc:
            _upload()
    assert exc.value.status_code == 502
    assert exc.value.detail == storage_service.SCREENSHOT_UPLOAD_FAILED_DETAIL


def test_a_refused_upload_is_a_502_without_supabases_body():
    put = AsyncMock(return_value=MagicMock(status_code=400, text="bucket issues-media-files: policy denied"))
    with patch("services.storage_service.httpx.AsyncClient", return_value=_client(put)):
        with pytest.raises(HTTPException) as exc:
            _upload()
    assert exc.value.status_code == 502
    assert "policy" not in exc.value.detail
    assert exc.value.detail == storage_service.SCREENSHOT_UPLOAD_FAILED_DETAIL


def test_a_stored_upload_returns_its_path():
    put = AsyncMock(return_value=MagicMock(status_code=200, text=""))
    with patch("services.storage_service.httpx.AsyncClient", return_value=_client(put)):
        path = _upload()
    assert path.startswith("user_1/") and path.endswith(".png")


def test_the_purge_reads_the_screenshot_bucket_from_its_owner():
    assert account_purge.ISSUE_BUCKET is storage_service.ISSUE_BUCKET
