"""Tests for IndexerClient — async HTTP proxy to rag-indexer.

All HTTP calls are intercepted with respx so no real network is required.
Tests cover:
  - resolve(): happy path, response deserialization, 4xx error propagation
  - apply(): happy path, 409 → IndexerConflictError, 5xx → IndexerUnavailableError
  - _post(): TransportError → IndexerUnavailableError
  - _extract_detail(): dict body / non-dict body / unparseable body
  - module-level singleton sanity
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.indexer_client import (
    IndexerClient,
    IndexerConflictError,
    IndexerUnavailableError,
    indexer_client,
)
from shared_contracts.models import (
    ResolvedUpdateModeChange,
    UpdateModeAction,
    UpdateModeApplyChange,
    UpdateModeApplyRequest,
    UpdateModeApplyResponse,
    UpdateModeChangeStatus,
    UpdateModeOperation,
    UpdateModeResolveRequest,
    UpdateModeResolveResponse,
    UpdateModeVaultApplyResult,
    UpdateModeVaultApplyStatus,
    UpdateModeAnchor,
    UpdateModeIntent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://test-indexer:8001"


def _client() -> IndexerClient:
    return IndexerClient(base_url=BASE_URL, timeout=5.0)


def _intent(
    change_id: str = "ch-1",
    action: UpdateModeAction = UpdateModeAction.UPDATE,
) -> UpdateModeIntent:
    return UpdateModeIntent(
        change_id=change_id,
        action=action,
        description="Add session recap",
        document_id="doc-1" if action == UpdateModeAction.UPDATE else None,
        operation=UpdateModeOperation.APPEND_TO_FILE,
        content="## Session recap\n\nPlayers arrived late.",
    )


def _resolve_request() -> UpdateModeResolveRequest:
    return UpdateModeResolveRequest(
        chat_id="chat-1",
        campaign_id="camp-1",
        domain_id="domain-1",
        vault_ids=["vault-1"],
        default_vault_id="vault-1",
        intents=[_intent()],
        candidate_document_ids=["doc-1"],
    )


def _resolved_change(
    change_id: str = "ch-1",
    status: UpdateModeChangeStatus = UpdateModeChangeStatus.PENDING,
) -> ResolvedUpdateModeChange:
    return ResolvedUpdateModeChange(
        change_id=change_id,
        vault_id="vault-1",
        document_id="doc-1",
        file_path="notes/session1.md",
        action=UpdateModeAction.UPDATE,
        description="Add session recap",
        original_content="# Session 1",
        proposed_content="# Session 1\n\n## Session recap\n\nPlayers arrived late.",
        unified_diff="@@ -1 +1,4 @@\n # Session 1\n+\n+## Session recap\n+\n+Players arrived late.",
        expected_sha256="abc123",
        status=status,
    )


def _apply_request() -> UpdateModeApplyRequest:
    return UpdateModeApplyRequest(
        apply_id=str(uuid.uuid4()),
        chat_id="chat-1",
        campaign_id="camp-1",
        accepted_changes=[
            UpdateModeApplyChange(
                change_id="ch-1",
                vault_id="vault-1",
                file_path="notes/session1.md",
                action=UpdateModeAction.UPDATE,
                proposed_content="# Session 1\n\n## Session recap\n\nPlayers arrived late.",
                expected_sha256="abc123",
            )
        ],
    )


def _vault_apply_result(
    status: UpdateModeVaultApplyStatus = UpdateModeVaultApplyStatus.APPLIED,
) -> UpdateModeVaultApplyResult:
    return UpdateModeVaultApplyResult(
        vault_id="vault-1",
        status=status,
        applied_count=1,
        commit_sha="deadbeef",
        commit_message="Update: Add session recap",
        reindex_task_id="task-123",
    )


# ---------------------------------------------------------------------------
# resolve() — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_success_deserializes_response() -> None:
    """resolve() returns typed UpdateModeResolveResponse on HTTP 200."""
    client = _client()
    request = _resolve_request()
    expected_response = UpdateModeResolveResponse(changes=[_resolved_change()])
    response_body = expected_response.model_dump(mode="json")

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = response_body

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        result = await client.resolve(request)

    assert isinstance(result, UpdateModeResolveResponse)
    assert len(result.changes) == 1
    assert result.changes[0].change_id == "ch-1"
    assert result.changes[0].status == UpdateModeChangeStatus.PENDING


@pytest.mark.asyncio
async def test_resolve_posts_to_correct_url() -> None:
    """resolve() posts to /internal/update-mode/resolve."""
    client = _client()
    request = _resolve_request()
    expected_response = UpdateModeResolveResponse(changes=[_resolved_change()])

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = expected_response.model_dump(mode="json")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        await client.resolve(request)

    called_url = mock_http_client.post.call_args.args[0]
    assert called_url == f"{BASE_URL}/internal/update-mode/resolve"


@pytest.mark.asyncio
async def test_resolve_serializes_request_payload() -> None:
    """resolve() sends correct JSON payload (chat_id, intents present)."""
    client = _client()
    request = _resolve_request()
    expected_response = UpdateModeResolveResponse(changes=[_resolved_change()])

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = expected_response.model_dump(mode="json")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        await client.resolve(request)

    payload = mock_http_client.post.call_args.kwargs["json"]
    assert payload["chat_id"] == "chat-1"
    assert payload["campaign_id"] == "camp-1"
    assert len(payload["intents"]) == 1
    assert payload["intents"][0]["change_id"] == "ch-1"


# ---------------------------------------------------------------------------
# resolve() — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_4xx_raises_indexer_unavailable() -> None:
    """resolve() raises IndexerUnavailableError on HTTP 422."""
    client = _client()
    request = _resolve_request()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 422
    mock_response.json.return_value = {"detail": "Validation error"}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerUnavailableError) as exc_info:
            await client.resolve(request)

    assert exc_info.value.status_code == 422
    assert "Validation error" in exc_info.value.detail


@pytest.mark.asyncio
async def test_resolve_transport_error_raises_indexer_unavailable() -> None:
    """resolve() raises IndexerUnavailableError on network failure."""
    client = _client()
    request = _resolve_request()

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerUnavailableError) as exc_info:
            await client.resolve(request)

    assert exc_info.value.status_code is None
    assert "rag-indexer" in exc_info.value.detail


# ---------------------------------------------------------------------------
# apply() — success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_success_deserializes_response() -> None:
    """apply() returns typed UpdateModeApplyResponse on HTTP 200."""
    client = _client()
    request = _apply_request()
    expected_response = UpdateModeApplyResponse(
        apply_id=request.apply_id,
        results=[_vault_apply_result()],
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = expected_response.model_dump(mode="json")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        result = await client.apply(request)

    assert isinstance(result, UpdateModeApplyResponse)
    assert result.apply_id == request.apply_id
    assert len(result.results) == 1
    assert result.results[0].status == UpdateModeVaultApplyStatus.APPLIED
    assert result.results[0].commit_sha == "deadbeef"


@pytest.mark.asyncio
async def test_apply_posts_to_correct_url() -> None:
    """apply() posts to /internal/update-mode/apply."""
    client = _client()
    request = _apply_request()
    expected_response = UpdateModeApplyResponse(
        apply_id=request.apply_id,
        results=[_vault_apply_result()],
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = expected_response.model_dump(mode="json")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        await client.apply(request)

    called_url = mock_http_client.post.call_args.args[0]
    assert called_url == f"{BASE_URL}/internal/update-mode/apply"


@pytest.mark.asyncio
async def test_apply_serializes_request_payload() -> None:
    """apply() sends correct JSON payload with apply_id and accepted_changes."""
    client = _client()
    request = _apply_request()
    expected_response = UpdateModeApplyResponse(
        apply_id=request.apply_id,
        results=[_vault_apply_result()],
    )

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = expected_response.model_dump(mode="json")

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        await client.apply(request)

    payload = mock_http_client.post.call_args.kwargs["json"]
    assert payload["apply_id"] == request.apply_id
    assert payload["chat_id"] == "chat-1"
    assert len(payload["accepted_changes"]) == 1
    assert payload["accepted_changes"][0]["change_id"] == "ch-1"
    assert payload["accepted_changes"][0]["expected_sha256"] == "abc123"


# ---------------------------------------------------------------------------
# apply() — error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_409_raises_indexer_conflict() -> None:
    """apply() raises IndexerConflictError on HTTP 409."""
    client = _client()
    request = _apply_request()
    conflict_detail = "SHA mismatch for notes/session1.md"

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 409
    mock_response.json.return_value = {"detail": conflict_detail}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerConflictError) as exc_info:
            await client.apply(request)

    assert conflict_detail in exc_info.value.detail


@pytest.mark.asyncio
async def test_apply_500_raises_indexer_unavailable() -> None:
    """apply() raises IndexerUnavailableError on HTTP 500."""
    client = _client()
    request = _apply_request()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 500
    mock_response.json.return_value = {"detail": "Internal Server Error"}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerUnavailableError) as exc_info:
            await client.apply(request)

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_apply_transport_error_raises_indexer_unavailable() -> None:
    """apply() raises IndexerUnavailableError on network failure."""
    client = _client()
    request = _apply_request()

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(
        side_effect=httpx.TimeoutException("Request timed out")
    )

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerUnavailableError) as exc_info:
            await client.apply(request)

    assert exc_info.value.status_code is None
    assert "rag-indexer" in exc_info.value.detail


# ---------------------------------------------------------------------------
# apply() — 409 is NOT raised as IndexerUnavailableError (type check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_409_is_conflict_not_unavailable() -> None:
    """409 on apply raises IndexerConflictError, NOT IndexerUnavailableError."""
    client = _client()
    request = _apply_request()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 409
    mock_response.json.return_value = {"detail": "conflict"}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerConflictError):
            await client.apply(request)


# ---------------------------------------------------------------------------
# resolve() — 409 raises IndexerUnavailableError (resolve does not allow_conflict)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_409_raises_unavailable_not_conflict() -> None:
    """resolve() does not set allow_conflict=True, so 409 → IndexerUnavailableError."""
    client = _client()
    request = _resolve_request()

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 409
    mock_response.json.return_value = {"detail": "unexpected conflict"}

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=None)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    with patch("app.services.indexer_client.httpx.AsyncClient", return_value=mock_http_client):
        with pytest.raises(IndexerUnavailableError):
            await client.resolve(request)


# ---------------------------------------------------------------------------
# _extract_detail() — unit tests
# ---------------------------------------------------------------------------


def test_extract_detail_dict_body() -> None:
    """Extracts 'detail' key from JSON dict body."""
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = {"detail": "something went wrong"}
    result = IndexerClient._extract_detail(response)
    assert result == "something went wrong"


def test_extract_detail_dict_body_no_detail_key() -> None:
    """Falls back to str(body) when 'detail' key is missing."""
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = {"error": "unknown"}
    result = IndexerClient._extract_detail(response)
    assert "unknown" in result


def test_extract_detail_non_dict_body() -> None:
    """Returns str of body when JSON is not a dict."""
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = ["error1", "error2"]
    result = IndexerClient._extract_detail(response)
    assert "error1" in result


def test_extract_detail_unparseable_body() -> None:
    """Falls back to response.text when JSON parsing fails."""
    response = MagicMock(spec=httpx.Response)
    response.json.side_effect = Exception("not JSON")
    response.text = "Internal Server Error"
    result = IndexerClient._extract_detail(response)
    assert result == "Internal Server Error"


# ---------------------------------------------------------------------------
# Constructor and singleton sanity
# ---------------------------------------------------------------------------


def test_client_base_url_stripped() -> None:
    """Trailing slash is stripped from base_url."""
    client = IndexerClient(base_url="http://indexer:8001/")
    assert client._base_url == "http://indexer:8001"


def test_module_singleton_is_indexer_client_instance() -> None:
    """Module-level indexer_client is an IndexerClient instance."""
    assert isinstance(indexer_client, IndexerClient)
