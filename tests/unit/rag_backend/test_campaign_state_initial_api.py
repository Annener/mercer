"""Tests for Campaign State — Stage 3 HTTP endpoints.

Endpoints under test:
  POST /api/settings/campaigns/{cid}/state/initial/preview
  GET  /api/settings/campaigns/{cid}/state/initial
  POST /api/settings/campaigns/{cid}/state/initial/apply

Strategy: in-memory fake of CampaignStateInitialService registered via
monkeypatch — same pattern as Stage 1/2 tests. The router raises typed
HTTPException based on service errors. Fake raises real exception classes
(imported from the service) so router's except clauses catch them.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any

import pytest
from app.api.settings import campaigns as api_module
from app.api.settings.campaigns import router
from app.db.session import get_db
from app.services.campaign_state_initial_service import (
    CampaignNotFoundError,
    DocumentNotMarkdownError,
    GenerationProviderUnavailableError,
    ProposalExpiredError,
    ProposalNotFoundError,
)
from app.services.campaign_state_value_service import (
    ConfigVersionConflictError,
    InitialAlreadyAppliedError,
    SourceSnapshotStaleError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import (
    CampaignStateInitialApplyRequestV2,
    CampaignStateInitialFieldStatus,
    CampaignStateInitialProposalField,
    CampaignStateInitialProposalReadV2,
    CampaignStateInitialProposalV2,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
    DocumentSnapshot,
)

# ---------------------------------------------------------------------------
# Fake service
# ---------------------------------------------------------------------------


class _FakeInitialService:
    def __init__(self) -> None:
        self.preview_calls: list[tuple[str, list[str], bool, int]] = []
        self.apply_calls: list[tuple[str, str, int]] = []
        self.get_calls: list[str] = []
        self.campaigns: set[str] = set()
        self.proposals: dict[str, CampaignStateInitialProposalReadV2] = {}

    async def assert_campaign_exists(self, db: Any, cid: uuid.UUID) -> None:
        if str(cid) not in self.campaigns:
            raise CampaignNotFoundError(str(cid))

    async def start_preview(
        self,
        db: Any,
        redis: Any,
        campaign_id: uuid.UUID,
        document_ids: list[str],
        current_user: str | None = None,
        *,
        propose_fields: bool = False,
        max_suggested_fields: int = 15,
    ) -> CampaignStateInitialProposalReadV2:
        self.preview_calls.append(
            (str(campaign_id), list(document_ids), propose_fields, max_suggested_fields)
        )
        cid = str(campaign_id)
        if cid not in self.campaigns:
            raise CampaignNotFoundError(cid)

        snap = DocumentSnapshot(
            document_id="11111111-1111-1111-1111-111111111111",
            vault_id="dnd-vault",
            source_path="session-14.md",
            content_sha="a" * 32,
            estimated_tokens=500,
        )
        pf = CampaignStateInitialProposalField(
            field_key="current_focus",
            mode="single",
            status=CampaignStateInitialFieldStatus(status="proposed"),
            single_value=None,
        )
        payload = CampaignStateInitialProposalReadV2(
            proposal_id=f"prop-{uuid.uuid4()}",
            campaign_id=cid,
            config_version=1,
            source_snapshot=[snap],
            proposal=CampaignStateInitialProposalV2(
                fields=[pf], suggested_fields=[], questions=[]
            ),
            warnings=["w1"],
            created_at=_dt.datetime.now(_dt.timezone.utc),
            expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
        )
        self.proposals[cid] = payload
        return payload

    async def get_proposal(
        self,
        redis: Any,
        campaign_id: uuid.UUID,
    ) -> CampaignStateInitialProposalReadV2 | None:
        self.get_calls.append(str(campaign_id))
        return self.proposals.get(str(campaign_id))

    async def apply(
        self,
        db: Any,
        redis: Any,
        campaign_id: uuid.UUID,
        request: CampaignStateInitialApplyRequestV2,
        current_user: str | None = None,
    ) -> CampaignStateVersionRead:
        self.apply_calls.append(
            (str(campaign_id), request.proposal_id, request.config_version)
        )
        cid = str(campaign_id)
        if cid not in self.campaigns:
            raise CampaignNotFoundError(cid)

        payload = self.proposals.get(cid)
        if payload is None:
            raise ProposalNotFoundError(cid)
        if payload.proposal_id != request.proposal_id:
            raise ProposalNotFoundError("proposal_id mismatch")

        # Построить фиктивный CampaignStateVersionRead.
        summary = CampaignStateVersionSummary(
            id=str(uuid.uuid4()),
            campaign_id=cid,
            state_version=1,
            config_version=request.config_version,
            source_kind="initial",
            base_state_version=None,
            created_at=_dt.datetime.now(_dt.timezone.utc),
            created_by=current_user,
        )
        from shared_contracts.models import CampaignStateFieldValuesRead

        return CampaignStateVersionRead(
            summary=summary,
            fields=[
                CampaignStateFieldValuesRead(
                    field_key="current_focus",
                    field_id=str(uuid.uuid4()),
                    mode="single",
                    enabled=True,
                    display_order=0,
                    single_value=CampaignStateSingleValueRead(
                        field_key="current_focus",
                        text="initial value",
                        source_refs=[],
                        updated_at=_dt.datetime.now(_dt.timezone.utc),
                    ),
                    items=[],
                )
            ],
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_service() -> _FakeInitialService:
    return _FakeInitialService()


@pytest.fixture
def client(monkeypatch, fake_service: _FakeInitialService):
    monkeypatch.setattr(api_module, "campaign_state_initial_service", fake_service)

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db

    # Подменяем request.app.state.redis через middleware-обёртку:
    # TestClient + FastAPI автоматически создают Request с app.state.redis,
    # если мы его выставим в app.state.
    fake_redis = object()
    app.state.redis = fake_redis
    return TestClient(app), fake_service


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def test_preview_empty_documents_returns_422(client):
    cli, _ = client
    cid = str(uuid.uuid4())
    body = {"document_ids": []}
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=body
    )
    assert r.status_code == 422


def test_preview_with_pdf_returns_422_via_service(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)
    # Подменим fake_service.start_preview на версию, бросающую DocumentNotMarkdownError.
    async def _raise(*a, **kw):
        raise DocumentNotMarkdownError("non-markdown")
    fake_service.start_preview = _raise  # type: ignore[method-assign]

    body = {"document_ids": [str(uuid.uuid4())]}
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=body
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "document_not_markdown"


def test_preview_returns_proposal_with_snapshot_sha(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)
    body = {"document_ids": [str(uuid.uuid4())]}
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=body
    )
    assert r.status_code == 200
    j = r.json()
    assert "proposal_id" in j
    assert j["campaign_id"] == cid
    assert j["config_version"] == 1
    assert len(j["source_snapshot"]) == 1
    assert j["source_snapshot"][0]["content_sha"] == "a" * 32
    assert j["warnings"] == ["w1"]


def test_preview_404_when_campaign_not_found(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    # Не добавляем cid в fake_service.campaigns.
    body = {"document_ids": [str(uuid.uuid4())]}
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=body
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "campaign_not_found"


def test_preview_503_when_no_provider(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    async def _raise(*a, **kw):
        raise GenerationProviderUnavailableError("no provider")
    fake_service.start_preview = _raise  # type: ignore[method-assign]

    body = {"document_ids": [str(uuid.uuid4())]}
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=body
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "generation_provider_unavailable"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


def test_get_returns_null_when_no_proposal(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)
    r = cli.get(f"/api/settings/campaigns/{cid}/state/initial")
    assert r.status_code == 200
    assert r.json() is None


def test_get_returns_existing_proposal(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    # Сначала делаем preview чтобы заполнить proposals.
    preview_body = {"document_ids": [str(uuid.uuid4())]}
    pr = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview", json=preview_body
    )
    assert pr.status_code == 200

    r = cli.get(f"/api/settings/campaigns/{cid}/state/initial")
    assert r.status_code == 200
    assert r.json()["campaign_id"] == cid
    assert r.json()["proposal_id"].startswith("prop-")


def test_get_404_when_campaign_missing(client):
    cli, _ = client
    cid = str(uuid.uuid4())
    r = cli.get(f"/api/settings/campaigns/{cid}/state/initial")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def test_apply_success_returns_state_version_1_with_initial(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    # preview
    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )
    proposal_id = fake_service.proposals[cid].proposal_id

    # apply
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": proposal_id, "config_version": 1},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["summary"]["state_version"] == 1
    assert j["summary"]["source_kind"] == "initial"
    assert j["summary"]["base_state_version"] is None


def test_apply_already_applied_returns_409(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )
    proposal_id = fake_service.proposals[cid].proposal_id

    async def _already(*a, **kw):
        raise InitialAlreadyAppliedError("already")
    fake_service.apply = _already  # type: ignore[method-assign]

    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": proposal_id, "config_version": 1},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "initial_already_applied"


def test_apply_snapshot_stale_returns_409_with_stale_documents(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )
    proposal_id = fake_service.proposals[cid].proposal_id

    stale_doc = str(uuid.uuid4())

    async def _stale(*a, **kw):
        raise SourceSnapshotStaleError(stale_documents=[stale_doc])
    fake_service.apply = _stale  # type: ignore[method-assign]

    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": proposal_id, "config_version": 1},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "source_snapshot_stale"
    assert detail["stale_documents"] == [stale_doc]


def test_apply_no_proposal_returns_404(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": "nope", "config_version": 1},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "proposal_not_found"


def test_apply_proposal_id_mismatch_returns_404(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )

    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": "wrong-id", "config_version": 1},
    )
    assert r.status_code == 404


def test_apply_config_version_conflict_returns_409(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )
    proposal_id = fake_service.proposals[cid].proposal_id

    async def _conflict(*a, **kw):
        raise ConfigVersionConflictError("drift")
    fake_service.apply = _conflict  # type: ignore[method-assign]

    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": proposal_id, "config_version": 99},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "config_version_conflict"


def test_apply_expired_proposal_returns_410(client, fake_service):
    cli, _ = client
    cid = str(uuid.uuid4())
    fake_service.campaigns.add(cid)

    cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/preview",
        json={"document_ids": [str(uuid.uuid4())]},
    )
    proposal_id = fake_service.proposals[cid].proposal_id

    async def _expired(*a, **kw):
        raise ProposalExpiredError("expired")
    fake_service.apply = _expired  # type: ignore[method-assign]

    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": proposal_id, "config_version": 1},
    )
    assert r.status_code == 410
    assert r.json()["detail"] == "proposal_expired"
