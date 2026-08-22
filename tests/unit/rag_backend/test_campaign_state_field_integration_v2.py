"""Tests for Campaign State field-config service (Stage 1) — Stage 2 integration.

Covers:
  - config_version is incremented on create / update / delete / reorder.
  - delete_field refuses when CampaignStateValue or CampaignStateListItem
    rows reference the field (FieldInUseError, 409).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.api.settings.campaigns import router
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fake service mirroring CampaignStateFieldService semantics + Stage 2 hooks
# ---------------------------------------------------------------------------


class _FakeField:
    def __init__(self, *, fid: str, campaign_id: str, key: str, mode: str) -> None:
        self.id = fid
        self.campaign_id = campaign_id
        self.key = key
        self.mode = mode
        self.label = "L"
        self.description = ""
        self.enabled = True
        self.display_order = 0


class _FakeFieldService:
    """Поведенческий дублёр, повторяющий правила Stage 2 для config_version."""

    def __init__(self) -> None:
        self._campaigns: dict[str, dict[str, Any]] = {}
        self._fields: dict[str, _FakeField] = {}
        # Какие field_id имеют ссылки в values/list_items.
        self.referenced_field_ids: set[str] = set()

    # --- helpers ---
    def register_campaign(self, cid: str, *, config_version: int = 1) -> None:
        self._campaigns[cid] = {"id": cid, "config_version": config_version}

    def mark_referenced(self, field_id: str) -> None:
        self.referenced_field_ids.add(field_id)

    # --- service interface ---

    async def list_fields(self, db, campaign_id):
        from app.services.campaign_state_service import CampaignNotFoundError
        if str(campaign_id) not in self._campaigns:
            raise CampaignNotFoundError(str(campaign_id))
        rows = [f for f in self._fields.values() if str(f.campaign_id) == str(campaign_id)]
        return [self._to_read(f) for f in rows]

    async def create_field(self, db, campaign_id, payload):
        from app.services.campaign_state_service import (
            CampaignNotFoundError,
            FieldKeyDuplicateError,
        )
        cid = str(campaign_id)
        if cid not in self._campaigns:
            raise CampaignNotFoundError(cid)
        if any(str(f.campaign_id) == cid and f.key == payload.key for f in self._fields.values()):
            raise FieldKeyDuplicateError("dup")
        fid = str(uuid.uuid4())
        f = _FakeField(fid=fid, campaign_id=cid, key=payload.key, mode=payload.mode)
        f.label = payload.label
        f.description = payload.description
        f.enabled = payload.enabled
        f.display_order = payload.display_order
        self._fields[fid] = f
        self._campaigns[cid]["config_version"] += 1
        return self._to_read(f)

    async def update_field(self, db, campaign_id, field_id, payload):
        from app.services.campaign_state_service import FieldNotFoundError
        f = self._fields.get(str(field_id))
        if f is None or str(f.campaign_id) != str(campaign_id):
            raise FieldNotFoundError(str(field_id))
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(f, k, v)
        self._campaigns[str(campaign_id)]["config_version"] += 1
        return self._to_read(f)

    async def delete_field(self, db, campaign_id, field_id):
        from app.services.campaign_state_service import (
            FieldInUseError,
            FieldNotFoundError,
        )
        f = self._fields.get(str(field_id))
        if f is None or str(f.campaign_id) != str(campaign_id):
            raise FieldNotFoundError(str(field_id))
        if str(field_id) in self.referenced_field_ids:
            raise FieldInUseError(f"field {f.key!r} is referenced by state")
        del self._fields[str(field_id)]
        self._campaigns[str(campaign_id)]["config_version"] += 1

    async def reorder_fields(self, db, campaign_id, ordered_field_ids):
        from app.services.campaign_state_service import (
            CampaignNotFoundError,
            InvalidReorderPayloadError,
        )
        cid = str(campaign_id)
        if cid not in self._campaigns:
            raise CampaignNotFoundError(cid)
        rows = [f for f in self._fields.values() if str(f.campaign_id) == cid]
        existing = {str(f.id) for f in rows}
        requested = set(ordered_field_ids)
        if existing != requested:
            raise InvalidReorderPayloadError("coverage mismatch")
        for idx, fid in enumerate(ordered_field_ids):
            self._fields[fid].display_order = idx
        self._campaigns[cid]["config_version"] += 1
        return await self.list_fields(db, campaign_id)

    def _to_read(self, f):
        from shared_contracts.models import CampaignStateFieldConfigRead
        return CampaignStateFieldConfigRead(
            id=str(f.id),
            campaign_id=str(f.campaign_id),
            key=f.key,
            label=f.label,
            description=f.description,
            mode=f.mode,
            enabled=f.enabled,
            display_order=f.display_order,
            created_at=None,
            updated_at=None,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> _FakeFieldService:
    return _FakeFieldService()


@pytest.fixture
def client(monkeypatch, service):
    from app.api.settings import campaigns as api_module
    monkeypatch.setattr(api_module, "campaign_state_field_service", service)
    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_bumps_config_version(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    )
    assert r.status_code == 201
    assert service._campaigns[cid]["config_version"] == 2


def test_update_bumps_config_version(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    assert service._campaigns[cid]["config_version"] == 2

    r = client.put(
        f"/api/settings/campaigns/{cid}/state-fields/{f['id']}",
        json={"label": "New"},
    )
    assert r.status_code == 200
    assert service._campaigns[cid]["config_version"] == 3


def test_reorder_bumps_config_version(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f1 = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "a", "label": "A", "mode": "single"},
    ).json()
    f2 = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "b", "label": "B", "mode": "single"},
    ).json()
    assert service._campaigns[cid]["config_version"] == 3

    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields/reorder",
        json={"field_ids": [f2["id"], f1["id"]]},
    )
    assert r.status_code == 200
    assert service._campaigns[cid]["config_version"] == 4


def test_delete_unreferenced_field_succeeds_and_bumps(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    assert service._campaigns[cid]["config_version"] == 2

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f['id']}")
    assert r.status_code == 204
    assert service._campaigns[cid]["config_version"] == 3


def test_delete_referenced_field_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    # Simulate that Stage 2 has stored a single-value for this field.
    service.mark_referenced(f["id"])
    # config_version is at 2 (create bumped it).
    assert service._campaigns[cid]["config_version"] == 2

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f['id']}")
    assert r.status_code == 409
    assert r.json()["detail"] == "field_in_use"
    # Field should still exist and config_version should NOT have been bumped.
    assert f["id"] in service._fields
    assert service._campaigns[cid]["config_version"] == 2