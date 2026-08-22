"""Tests for Campaign State — Stage 2 read endpoints.

Endpoints under test:
  GET /api/settings/campaigns/{cid}/state
  GET /api/settings/campaigns/{cid}/state/versions
  GET /api/settings/campaigns/{cid}/state/versions/{state_version}

Strategy: in-memory fake of CampaignStateValueService registered into the
router via monkeypatch — same pattern as Stage 1 tests.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.api.settings.campaigns import router
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import (
    CampaignStateFieldValuesRead,
    CampaignStateListItemRead,
    CampaignStateSingleValueRead,
    CampaignStateVersionRead,
    CampaignStateVersionSummary,
)

# ---------------------------------------------------------------------------
# In-memory fake service
# ---------------------------------------------------------------------------


class _FakeValueService:
    def __init__(self) -> None:
        self._campaigns: dict[str, dict[str, Any]] = {}  # cid -> campaign info
        self._versions: dict[str, list[dict[str, Any]]] = {}  # cid -> ordered list (DESC)
        self._fields_by_campaign: dict[str, list[dict[str, Any]]] = {}

    # --- test helpers ---
    def register_campaign(self, campaign_id: str, *, config_version: int = 1) -> None:
        self._campaigns[campaign_id] = {"id": campaign_id, "config_version": config_version}
        self._versions.setdefault(campaign_id, [])
        self._fields_by_campaign.setdefault(campaign_id, [])

    def add_field(
        self,
        campaign_id: str,
        key: str,
        mode: str,
        *,
        field_id: str | None = None,
        enabled: bool = True,
        display_order: int = 0,
    ) -> str:
        fid = field_id or str(uuid.uuid4())
        self._fields_by_campaign[campaign_id].append(
            {
                "id": fid,
                "key": key,
                "mode": mode,
                "enabled": enabled,
                "display_order": display_order,
            }
        )
        return fid

    def add_version(
        self,
        campaign_id: str,
        state_version: int,
        *,
        values: list[dict[str, Any]] | None = None,
        list_items: list[dict[str, Any]] | None = None,
        source_kind: str = "patch",
        config_version: int | None = None,
        base_state_version: int | None = None,
    ) -> None:
        cfg = (
            config_version
            if config_version is not None
            else self._campaigns[campaign_id]["config_version"]
        )
        self._versions[campaign_id].append(
            {
                "id": str(uuid.uuid4()),
                "campaign_id": campaign_id,
                "state_version": state_version,
                "config_version": cfg,
                "source_kind": source_kind,
                "base_state_version": base_state_version,
                "created_at": None,
                "created_by": None,
                "values": values or [],
                "list_items": list_items or [],
            }
        )

    # --- service interface used by the router ---

    async def get_active_state(self, db: Any, campaign_id: uuid.UUID):
        cid = str(campaign_id)
        if cid not in self._campaigns:
            from app.services.campaign_state_value_service import CampaignNotFoundError
            raise CampaignNotFoundError(cid)
        rows = self._versions.get(cid, [])
        if not rows:
            return None
        # Highest state_version first.
        rows_sorted = sorted(rows, key=lambda r: r["state_version"], reverse=True)
        return self._serialize(cid, rows_sorted[0])

    async def get_state_version(self, db: Any, campaign_id: uuid.UUID, state_version: int):
        cid = str(campaign_id)
        if cid not in self._campaigns:
            from app.services.campaign_state_value_service import CampaignNotFoundError
            raise CampaignNotFoundError(cid)
        for r in self._versions.get(cid, []):
            if r["state_version"] == state_version:
                return self._serialize(cid, r)
        return None

    async def list_versions(
        self, db: Any, campaign_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ):
        cid = str(campaign_id)
        if cid not in self._campaigns:
            from app.services.campaign_state_value_service import CampaignNotFoundError
            raise CampaignNotFoundError(cid)
        rows = sorted(
            self._versions.get(cid, []),
            key=lambda r: r["state_version"],
            reverse=True,
        )
        out: list[CampaignStateVersionSummary] = []
        for r in rows[offset : offset + limit]:
            out.append(self._summary(r))
        return out

    # --- serialization helpers ---

    def _summary(self, row: dict[str, Any]) -> CampaignStateVersionSummary:
        return CampaignStateVersionSummary(
            id=row["id"],
            campaign_id=row["campaign_id"],
            state_version=row["state_version"],
            config_version=row["config_version"],
            source_kind=row["source_kind"],
            base_state_version=row["base_state_version"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )

    def _serialize(self, cid: str, row: dict[str, Any]) -> CampaignStateVersionRead:
        summary = self._summary(row)
        fields_data = self._fields_by_campaign.get(cid, [])

        values_by_field_id: dict[str, dict[str, Any]] = {v["field_id"]: v for v in row["values"]}
        items_by_field_id: dict[str, list[dict[str, Any]]] = {}
        for it in row["list_items"]:
            items_by_field_id.setdefault(it["field_id"], []).append(it)

        field_values: list[CampaignStateFieldValuesRead] = []
        for f in fields_data:
            if f["mode"] == "single":
                v = values_by_field_id.get(f["id"])
                single = (
                    CampaignStateSingleValueRead(
                        field_key=f["key"],
                        text=v["text"],
                        source_refs=list(v.get("source_refs", [])),
                        updated_at=v.get("updated_at"),
                    )
                    if v is not None
                    else None
                )
                field_values.append(
                    CampaignStateFieldValuesRead(
                        field_key=f["key"],
                        field_id=f["id"],
                        mode="single",
                        enabled=f["enabled"],
                        display_order=f["display_order"],
                        single_value=single,
                        items=[],
                    )
                )
            else:
                items = items_by_field_id.get(f["id"], [])
                field_values.append(
                    CampaignStateFieldValuesRead(
                        field_key=f["key"],
                        field_id=f["id"],
                        mode="list",
                        enabled=f["enabled"],
                        display_order=f["display_order"],
                        single_value=None,
                        items=[
                            CampaignStateListItemRead(
                                field_key=f["key"],
                                item_key=it["item_key"],
                                text=it["text"],
                                resolved=it.get("resolved", False),
                                source_refs=list(it.get("source_refs", [])),
                                updated_at=it.get("updated_at"),
                            )
                            for it in items
                        ],
                    )
                )
        return CampaignStateVersionRead(summary=summary, fields=field_values)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> _FakeValueService:
    return _FakeValueService()


@pytest.fixture
def client(monkeypatch, service):
    # Router uses a bound import: `from ... import campaign_state_value_service`.
    # Patch the symbol in the router's module namespace so the route handlers
    # see the fake service.
    from app.api.settings import campaigns as api_module

    monkeypatch.setattr(api_module, "campaign_state_value_service", service)

    app = FastAPI()
    # Mirror the production mount prefix from rag-backend/app/main.py
    app.include_router(router, prefix="/api/settings")

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_active_state_no_versions_returns_null(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    r = client.get(f"/api/settings/campaigns/{cid}/state")
    assert r.status_code == 200
    assert r.json() is None


def test_get_active_state_returns_latest(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    fid_single = service.add_field(cid, "current_focus", "single", display_order=0)
    fid_list = service.add_field(cid, "agreements", "list", display_order=1)

    service.add_version(
        cid,
        1,
        values=[
            {"field_id": fid_single, "text": "Focus v1", "source_refs": []},
        ],
        list_items=[
            {"field_id": fid_list, "item_key": "agreements-01", "text": "A1", "source_refs": []},
        ],
    )
    service.add_version(
        cid,
        2,
        values=[
            {"field_id": fid_single, "text": "Focus v2", "source_refs": []},
        ],
        list_items=[
            {"field_id": fid_list, "item_key": "agreements-01", "text": "A1", "source_refs": []},
            {"field_id": fid_list, "item_key": "agreements-02", "text": "A2", "source_refs": []},
        ],
    )

    r = client.get(f"/api/settings/campaigns/{cid}/state")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["state_version"] == 2
    fields = {f["field_key"]: f for f in body["fields"]}
    assert fields["current_focus"]["single_value"]["text"] == "Focus v2"
    assert fields["agreements"]["mode"] == "list"
    assert [it["item_key"] for it in fields["agreements"]["items"]] == ["agreements-01", "agreements-02"]


def test_get_specific_version(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    fid = service.add_field(cid, "focus", "single")

    service.add_version(cid, 1, values=[{"field_id": fid, "text": "v1", "source_refs": []}])
    service.add_version(cid, 2, values=[{"field_id": fid, "text": "v2", "source_refs": []}])

    r = client.get(f"/api/settings/campaigns/{cid}/state/versions/1")
    assert r.status_code == 200
    assert r.json()["summary"]["state_version"] == 1

    r = client.get(f"/api/settings/campaigns/{cid}/state/versions/999")
    assert r.status_code == 200
    assert r.json() is None


def test_list_versions_desc(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    for v in (1, 2, 3, 4):
        service.add_version(cid, v)

    r = client.get(f"/api/settings/campaigns/{cid}/state/versions")
    assert r.status_code == 200
    versions = [s["state_version"] for s in r.json()]
    assert versions == [4, 3, 2, 1]


def test_list_versions_with_pagination(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    for v in range(1, 6):
        service.add_version(cid, v)

    r = client.get(f"/api/settings/campaigns/{cid}/state/versions?limit=2&offset=1")
    assert r.status_code == 200
    versions = [s["state_version"] for s in r.json()]
    assert versions == [4, 3]


def test_get_state_campaign_not_found(client):
    missing = str(uuid.uuid4())
    r = client.get(f"/api/settings/campaigns/{missing}/state")
    assert r.status_code == 404
    assert r.json()["detail"] == "campaign_not_found"


def test_list_versions_campaign_not_found(client):
    missing = str(uuid.uuid4())
    r = client.get(f"/api/settings/campaigns/{missing}/state/versions")
    assert r.status_code == 404
    assert r.json()["detail"] == "campaign_not_found"