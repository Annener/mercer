"""Tests for Campaign State field-config service (Stage 1) — Stage 2 integration.

Covers:
  - config_version is incremented on create / update / delete / reorder.
  - delete_field cascade-purges the value in the active state version,
    creates a new state_version, writes an audit row, and bumps
    config_version. Past state_versions are not touched.
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


class _FakeAuditEntry:
    def __init__(self, **kwargs: Any) -> None:
        self.action = kwargs.get("action")
        self.entity_type = kwargs.get("entity_type")
        self.entity_id = kwargs.get("entity_id")
        self.actor = kwargs.get("actor")
        self.payload = kwargs.get("payload") or {}


class _FakeFieldService:
    """Поведенческий дублёр, повторяющий правила Stage 2 для config_version."""

    def __init__(self) -> None:
        self._campaigns: dict[str, dict[str, Any]] = {}
        self._fields: dict[str, _FakeField] = {}
        # field_id → тип ('single' | 'list') для симуляции значения в active state.
        self.referenced_field_ids: dict[str, str] = {}
        # История state_versions: список dict-ов.
        self.state_versions: list[dict[str, Any]] = []
        # Снимок audit-trail для проверки записей.
        self.audit_log: list[_FakeAuditEntry] = []
        # Контракт: при удалении с active_state — писать audit или нет.
        # По умолчанию — да (mirror production).

    # --- helpers ---
    def register_campaign(self, cid: str, *, config_version: int = 1) -> None:
        self._campaigns[cid] = {"id": cid, "config_version": config_version}

    def mark_referenced(self, field_id: str, kind: str = "single") -> None:
        self.referenced_field_ids[field_id] = kind

    def add_active_state_version(self, version: int) -> None:
        self.state_versions.append(
            {"state_version": version, "values": set(), "list_items": set()}
        )

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

    async def delete_field(self, db, campaign_id, field_id, created_by=None):
        from app.services.campaign_state_service import FieldNotFoundError
        f = self._fields.get(str(field_id))
        if f is None or str(f.campaign_id) != str(campaign_id):
            raise FieldNotFoundError(str(field_id))

        cid = str(campaign_id)
        latest = self.state_versions[-1] if self.state_versions else None

        if latest is None:
            del self._fields[str(field_id)]
            self._campaigns[cid]["config_version"] += 1
            return

        # Cascade: считаем, сколько значений/list-items относится к этому полю
        # в latest, и в новой версии исключаем их. Сам latest не трогаем —
        # аудит-трейл прошлых state_versions остаётся неизменным.
        purged_values = 1 if str(field_id) in latest["values"] else 0
        purged_list_items = 1 if str(field_id) in latest["list_items"] else 0

        # Snapshot config_version BEFORE bump.
        snapshotted_config_version = self._campaigns[cid]["config_version"]
        new_state_version = latest["state_version"] + 1
        new_values = set(latest["values"])
        new_values.discard(str(field_id))
        new_items = set(latest["list_items"])
        new_items.discard(str(field_id))
        self.state_versions.append(
            {
                "state_version": new_state_version,
                "base_state_version": latest["state_version"],
                "config_version": snapshotted_config_version,
                "source_kind": "patch",
                "values": new_values,
                "list_items": new_items,
            }
        )

        self.audit_log.append(
            _FakeAuditEntry(
                action="campaign_state_field_cascade_purged",
                entity_type="campaign",
                entity_id=cid,
                actor=created_by,
                payload={
                    "from_state_version": latest["state_version"],
                    "to_state_version": new_state_version,
                    "config_version": snapshotted_config_version,
                    "field_id": str(field_id),
                    "field_key": f.key,
                    "purged_values": purged_values,
                    "purged_list_items": purged_list_items,
                },
            )
        )

        del self._fields[str(field_id)]
        self._campaigns[cid]["config_version"] += 1

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
    """Сценарий «без active state» — нет каскадной версии, audit не пишется."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    assert service._campaigns[cid]["config_version"] == 2
    # state_versions пуст — ни одной active version.
    assert service.state_versions == []

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f['id']}")
    assert r.status_code == 204
    assert service._campaigns[cid]["config_version"] == 3
    # Audit не пишется, если state_versions пуст.
    assert service.audit_log == []
    assert f["id"] not in service._fields


def test_delete_referenced_field_cascades_and_bumps_state(client, service):
    """Каскадное удаление: новая state_version + audit, config_version bump-нут."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    # Активная версия уже есть; в ней значение для этого поля.
    service.add_active_state_version(version=1)
    service.state_versions[-1]["values"].add(f["id"])
    assert service._campaigns[cid]["config_version"] == 2

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f['id']}")
    assert r.status_code == 204
    # Поле удалено.
    assert f["id"] not in service._fields
    # config_version инкрементирован.
    assert service._campaigns[cid]["config_version"] == 3
    # Появилась новая state_version, base указывает на 1.
    assert len(service.state_versions) == 2
    new_v = service.state_versions[-1]
    assert new_v["state_version"] == 2
    assert new_v["base_state_version"] == 1
    assert new_v["source_kind"] == "patch"
    # config_version в снапшоте — ДО bump (=2), не после (=3).
    assert new_v["config_version"] == 2
    # Значение удалено в новой версии.
    assert f["id"] not in new_v["values"]
    # Audit-записана.
    assert len(service.audit_log) == 1
    entry = service.audit_log[0]
    assert entry.action == "campaign_state_field_cascade_purged"
    assert entry.entity_type == "campaign"
    assert entry.entity_id == cid
    assert entry.payload["from_state_version"] == 1
    assert entry.payload["to_state_version"] == 2
    assert entry.payload["config_version"] == 2
    assert entry.payload["field_id"] == f["id"]
    assert entry.payload["field_key"] == "focus"
    assert entry.payload["purged_values"] == 1
    assert entry.payload["purged_list_items"] == 0


def test_delete_field_with_no_active_state_writes_no_audit(client, service):
    """Активной state_version нет — удаляем поле без каскадной версии и без audit."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    # state_versions пуст.
    assert service.state_versions == []

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f['id']}")
    assert r.status_code == 204
    assert service.audit_log == []
    assert service.state_versions == []
    assert service._campaigns[cid]["config_version"] == 3


def test_delete_field_keeps_previous_state_versions_intact(client, service):
    """Прошлая state_version сохраняет свои значения; новая — без удалённого поля."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f_focus = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "focus", "label": "Focus", "mode": "single"},
    ).json()
    f_agree = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "agreements", "label": "A", "mode": "list"},
    ).json()
    # v1 содержит оба поля.
    service.add_active_state_version(version=1)
    service.state_versions[-1]["values"].add(f_focus["id"])
    service.state_versions[-1]["list_items"].add(f_agree["id"])
    pre_versions = list(service.state_versions)

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f_focus["id"]}")
    assert r.status_code == 204
    # v1 не тронута (всё ещё содержит focus).
    assert service.state_versions[0]["values"] == pre_versions[0]["values"]
    assert f_focus["id"] in service.state_versions[0]["values"]
    # v2 — копия v1 минус focus.
    v2 = service.state_versions[1]
    assert f_focus["id"] not in v2["values"]
    assert f_agree["id"] in v2["list_items"]


def test_delete_list_field_cascades_list_items(client, service):
    """Каскад для list-поля: purged_list_items=1, values=0."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid, config_version=1)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "agreements", "label": "A", "mode": "list"},
    ).json()
    service.add_active_state_version(version=1)
    service.state_versions[-1]["list_items"].add(f["id"])

    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f["id"]}")
    assert r.status_code == 204
    entry = service.audit_log[0]
    assert entry.payload["purged_values"] == 0
    assert entry.payload["purged_list_items"] == 1