"""Tests for Stage 3.v2 HTTP endpoints (propose_fields flow).

Стратегия: регистрируем fake-сервис через monkeypatch; проверяем, что:
  - POST /preview корректно прокидывает propose_fields и max_suggested_fields;
  - 422 при 0 полей и propose_fields=false;
  - preview с propose_fields=true возвращает suggested_fields;
  - apply с accepted_suggested_field_keys корректно вызывает сервис;
  - apply без suggested_fields работает в backward-compat режиме.
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
    NoFieldsConfiguredNoProposeError,
    ProposalExpiredError,
    SuggestedFieldCreationError,
    SuggestedFieldKeyConflictError,
)
from app.services.campaign_state_value_service import (
    ConfigVersionConflictError,
    InitialAlreadyAppliedError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import (
    CampaignStateFieldValuesRead,
    CampaignStateInitialApplyRequestV2,
    CampaignStateInitialProposalReadV2,
    CampaignStateInitialProposalV2,
    CampaignStateInitialSingleValue,
    CampaignStateSuggestedFieldConfig,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
    DocumentSnapshot,
)


class _FakeInitialServiceV2:
    def __init__(self) -> None:
        self.preview_calls: list[tuple[str, list[str], bool, int]] = []
        self.apply_calls: list[tuple[str, str, int, list[str], list[str]]] = []
        self.campaigns: set[str] = set()
        # Кастомный ответ preview (по умолчанию минимальный).
        self.next_preview_payload: CampaignStateInitialProposalReadV2 | None = None
        # Кастомная ошибка при apply (если задана).
        self.apply_error: Exception | None = None

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

        # Специальный сценарий: 0 полей без propose_fields.
        if not propose_fields:
            raise NoFieldsConfiguredNoProposeError("0 fields, no propose_fields")

        if self.next_preview_payload is not None:
            return self.next_preview_payload

        # Иначе — минимальный полезный payload c 1 suggested field.
        snap = DocumentSnapshot(
            document_id="11111111-1111-1111-1111-111111111111",
            vault_id="dnd-vault",
            source_path="session-14.md",
            content_sha="a" * 32,
            estimated_tokens=500,
        )
        sf = CampaignStateSuggestedFieldConfig(
            key="character_goals",
            label="Цели персонажа",
            description="",
            mode="single",
            initial_status="proposed",
            single_value=CampaignStateInitialSingleValue(text="Найти артефакт"),
        )
        payload = CampaignStateInitialProposalReadV2(
            proposal_id=f"prop-{uuid.uuid4()}",
            campaign_id=cid,
            config_version=1,
            source_snapshot=[snap],
            proposal=CampaignStateInitialProposalV2(
                fields=[],
                suggested_fields=[sf],
                questions=["Кто главный злодей?"],
            ),
            warnings=[],
            created_at=_dt.datetime.now(_dt.timezone.utc),
            expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
        )
        self._last_preview_payload = payload
        return payload

    async def get_proposal(
        self,
        redis: Any,
        campaign_id: uuid.UUID,
    ) -> CampaignStateInitialProposalReadV2 | None:
        if hasattr(self, "_last_preview_payload") and \
                self._last_preview_payload.campaign_id == str(campaign_id):
            return self._last_preview_payload
        return None

    async def apply(
        self,
        db: Any,
        redis: Any,
        campaign_id: uuid.UUID,
        request: CampaignStateInitialApplyRequestV2,
        current_user: str | None = None,
    ) -> CampaignStateVersionRead:
        self.apply_calls.append(
            (
                str(campaign_id),
                request.proposal_id,
                request.config_version,
                list(request.accepted_suggested_field_keys),
                list(request.rejected_suggested_field_keys),
            )
        )
        cid = str(campaign_id)
        if cid not in self.campaigns:
            raise CampaignNotFoundError(cid)
        if self.apply_error is not None:
            raise self.apply_error

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
        from shared_contracts.models import CampaignStateSingleValueRead

        return CampaignStateVersionRead(
            summary=summary,
            fields=[
                CampaignStateFieldValuesRead(
                    field_key="character_goals",
                    field_id=str(uuid.uuid4()),
                    mode="single",
                    enabled=True,
                    display_order=0,
                    single_value=CampaignStateSingleValueRead(
                        field_key="character_goals",
                        text="value",
                        source_refs=[],
                        updated_at=_dt.datetime.now(_dt.timezone.utc),
                    ),
                    items=[],
                )
            ],
        )


@pytest.fixture
def fake_service_v2() -> _FakeInitialServiceV2:
    return _FakeInitialServiceV2()


@pytest.fixture
def client_v2(monkeypatch, fake_service_v2: _FakeInitialServiceV2):
    monkeypatch.setattr(api_module, "campaign_state_initial_service", fake_service_v2)

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    app.state.redis = object()
    return TestClient(app), fake_service_v2


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------


def test_preview_v2_422_when_no_fields_and_propose_fields_false(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    body = {"document_ids": [str(uuid.uuid4())], "propose_fields": False}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 422
    assert r.json()["detail"] == "no_fields_configured_no_propose"


def test_preview_v2_passes_propose_fields_and_max_to_service(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    body = {
        "document_ids": [str(uuid.uuid4())],
        "propose_fields": True,
        "max_suggested_fields": 7,
    }
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 200
    assert fake.preview_calls[0][2] is True
    assert fake.preview_calls[0][3] == 7


def test_preview_v2_default_propose_fields_false(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    body = {"document_ids": [str(uuid.uuid4())]}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    # Без propose_fields наш fake бросает 422, но мы хотим проверить,
    # что дефолтный флаг правильно прокидывается.
    assert r.status_code == 422


def test_preview_v2_returns_suggested_fields(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    body = {
        "document_ids": [str(uuid.uuid4())],
        "propose_fields": True,
    }
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 200
    j = r.json()
    assert "proposal" in j
    assert "suggested_fields" in j["proposal"]
    assert len(j["proposal"]["suggested_fields"]) == 1
    assert j["proposal"]["suggested_fields"][0]["key"] == "character_goals"
    assert j["proposal"]["suggested_fields"][0]["single_value"]["text"] == "Найти артефакт"


def test_preview_v2_empty_documents_returns_422(client_v2):
    cli, _ = client_v2
    cid = str(uuid.uuid4())
    body = {"document_ids": [], "propose_fields": True}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 422


def test_preview_v2_max_suggested_fields_above_50_returns_422(client_v2):
    cli, _ = client_v2
    cid = str(uuid.uuid4())
    body = {
        "document_ids": [str(uuid.uuid4())],
        "propose_fields": True,
        "max_suggested_fields": 51,
    }
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 422


def test_preview_v2_404_when_campaign_not_found(client_v2):
    cli, _ = client_v2
    cid = str(uuid.uuid4())
    body = {"document_ids": [str(uuid.uuid4())], "propose_fields": True}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/preview", json=body)
    assert r.status_code == 404
    assert r.json()["detail"] == "campaign_not_found"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


def test_apply_v2_passes_accepted_and_rejected_keys(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(
            fields=[],
            suggested_fields=[
                CampaignStateSuggestedFieldConfig(
                    key="a", label="A", mode="single",
                    initial_status="proposed",
                    single_value=CampaignStateInitialSingleValue(text="x"),
                ),
                CampaignStateSuggestedFieldConfig(
                    key="b", label="B", mode="single",
                    initial_status="proposed",
                    single_value=CampaignStateInitialSingleValue(text="y"),
                ),
            ],
            questions=[],
        ),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    body = {
        "proposal_id": "prop-1",
        "config_version": 1,
        "accepted_suggested_field_keys": ["a"],
        "rejected_suggested_field_keys": ["b"],
    }
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 200
    assert fake.apply_calls[0][3] == ["a"]
    assert fake.apply_calls[0][4] == ["b"]


def test_apply_v2_backward_compat_no_accepted_keys(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    body = {"proposal_id": "prop-1", "config_version": 1}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 200
    assert fake.apply_calls[0][3] == []
    assert fake.apply_calls[0][4] == []


def test_apply_v2_suggested_key_conflict_returns_409(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    fake.apply_error = SuggestedFieldKeyConflictError("'x' already exists")
    body = {"proposal_id": "prop-1", "config_version": 1,
            "accepted_suggested_field_keys": ["x"]}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "suggested_field_key_conflict"


def test_apply_v2_suggested_creation_failed_returns_409(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    fake.apply_error = SuggestedFieldCreationError("boom")
    body = {"proposal_id": "prop-1", "config_version": 1}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "suggested_field_creation_failed"


def test_apply_v2_initial_already_applied_returns_409(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    fake.apply_error = InitialAlreadyAppliedError("already")
    body = {"proposal_id": "prop-1", "config_version": 1}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "initial_already_applied"


def test_apply_v2_proposal_expired_returns_410(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    fake.apply_error = ProposalExpiredError("expired")
    body = {"proposal_id": "prop-1", "config_version": 1}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 410


def test_apply_v2_config_version_conflict_returns_409(client_v2):
    cli, fake = client_v2
    cid = str(uuid.uuid4())
    fake.campaigns.add(cid)
    fake._last_preview_payload = CampaignStateInitialProposalReadV2(
        proposal_id="prop-1",
        campaign_id=cid,
        config_version=1,
        source_snapshot=[],
        proposal=CampaignStateInitialProposalV2(fields=[], suggested_fields=[]),
        warnings=[],
        created_at=_dt.datetime.now(_dt.timezone.utc),
        expires_at=_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3),
    )
    fake.apply_error = ConfigVersionConflictError("drift")
    body = {"proposal_id": "prop-1", "config_version": 99}
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "config_version_conflict"


def test_apply_v2_proposal_not_found_returns_404(client_v2):
    cli, _ = client_v2
    cid = str(uuid.uuid4())
    r = cli.post(
        f"/api/settings/campaigns/{cid}/state/initial/apply",
        json={"proposal_id": "nope", "config_version": 1},
    )
    # Нет campaign в fake → 404 campaign_not_found
    assert r.status_code == 404


def test_apply_v2_more_than_50_accepted_returns_422(client_v2):
    cli, _ = client_v2
    cid = str(uuid.uuid4())
    body = {
        "proposal_id": "p",
        "config_version": 1,
        "accepted_suggested_field_keys": ["k" for _ in range(51)],
    }
    r = cli.post(f"/api/settings/campaigns/{cid}/state/initial/apply", json=body)
    assert r.status_code == 422
