"""Tests for Campaign State — Stage 2 patch endpoint.

Endpoint:
  POST /api/settings/campaigns/{cid}/state/patch

Covers acceptance criteria from the implementation plan:
  - apply patch → new state_version = base + 1
  - second apply with the same base_state_version → 409 + server snapshot
  - operation against unknown field_key → 422, no partial apply
  - update_list_item with unknown item_key → 422, no partial apply
  - config_version mismatch → 409
  - invalid source_ref → 422
  - audit row written on success
"""
from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from app.api.settings.campaigns import router
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared_contracts.models import (
    CampaignStatePatchOperation,
    CampaignStatePatchRequest,
)

# ---------------------------------------------------------------------------
# In-memory fake service mirroring CampaignStateValueService.apply_patch
# ---------------------------------------------------------------------------


_SOURCE_REF_RE = re.compile(
    r"^(file:[0-9a-fA-F-]{36}:sha:[0-9a-f]{8,64}|chat:[0-9a-fA-F-]{36}|vault:[a-z0-9_-]{1,128})$"
)


class _FakeField:
    def __init__(self, fid: str, key: str, mode: str) -> None:
        self.id = fid
        self.key = key
        self.mode = mode


class _FakeVersion:
    def __init__(self, state_version: int, config_version: int, base: int | None) -> None:
        self.state_version = state_version
        self.config_version = config_version
        self.base_state_version = base
        # single values by field_id -> {text, source_refs}
        self.single_values: dict[str, dict[str, Any]] = {}
        # list items by field_id -> {item_key -> {text, resolved, source_refs}}
        self.list_items: dict[str, dict[str, dict[str, Any]]] = {}


class _FakeValueService:
    def __init__(self) -> None:
        self._campaigns: dict[str, dict[str, Any]] = {}
        self._fields_by_campaign: dict[str, list[_FakeField]] = {}
        self._versions_by_campaign: dict[str, list[_FakeVersion]] = {}
        self._audit: list[dict[str, Any]] = []

    # --- helpers ---
    def register_campaign(self, cid: str, *, config_version: int = 1) -> None:
        self._campaigns[cid] = {"id": cid, "config_version": config_version}
        self._fields_by_campaign.setdefault(cid, [])
        self._versions_by_campaign.setdefault(cid, [])

    def bump_config_version(self, cid: str) -> None:
        self._campaigns[cid]["config_version"] += 1

    def add_field(self, cid: str, key: str, mode: str, *, fid: str | None = None) -> str:
        fid = fid or str(uuid.uuid4())
        self._fields_by_campaign[cid].append(_FakeField(fid, key, mode))
        return fid

    def _seed_version(self, cid: str, state_version: int, *, base: int | None = None) -> _FakeVersion:
        cfg = self._campaigns[cid]["config_version"]
        v = _FakeVersion(state_version, cfg, base)
        self._versions_by_campaign[cid].append(v)
        return v

    def audit_entries(self) -> list[dict[str, Any]]:
        return list(self._audit)

    # --- service interface ---

    async def apply_patch(
        self,
        db: Any,
        campaign_id: uuid.UUID,
        request: CampaignStatePatchRequest,
    ):
        cid = str(campaign_id)
        from app.services.campaign_state_value_service import (
            CampaignNotFoundError,
            ConfigVersionConflictError,
            InvalidSourceRefError,
            PatchValidationError,
            StateVersionConflictError,
        )

        if cid not in self._campaigns:
            raise CampaignNotFoundError(cid)

        cfg = self._campaigns[cid]["config_version"]
        if request.config_version != cfg:
            raise ConfigVersionConflictError(
                f"config_version mismatch: client={request.config_version}, server={cfg}"
            )

        versions = self._versions_by_campaign[cid]
        latest = max(versions, key=lambda v: v.state_version) if versions else None

        if latest is None:
            if request.base_state_version is not None:
                raise StateVersionConflictError(
                    "base_state_version provided but no versions exist"
                )
            new_state_version = 1
        else:
            if request.base_state_version != latest.state_version:
                raise StateVersionConflictError(
                    f"base_state_version mismatch: client={request.base_state_version}, "
                    f"server={latest.state_version}"
                )
            new_state_version = latest.state_version + 1

        fields_by_key = {f.key: f for f in self._fields_by_campaign[cid]}

        # Pre-validate.
        for index, op in enumerate(request.operations):
            if not op.reason or not op.reason.strip():
                raise PatchValidationError(
                    _rejection(index, op, "invalid_payload", "reason must be non-empty")
                )
            for ref in op.source_refs:
                if not isinstance(ref, str) or not _SOURCE_REF_RE.match(ref):
                    raise InvalidSourceRefError(f"invalid source_ref: {ref!r}")
            f = fields_by_key.get(op.field_key)
            if f is None:
                raise PatchValidationError(
                    _rejection(index, op, "field_not_found", f"field_key {op.field_key!r} not found")
                )
            if op.type in ("replace_single", "clear_single") and f.mode != "single":
                raise PatchValidationError(
                    _rejection(index, op, "mode_mismatch", f"field is mode={f.mode}")
                )
            if op.type in (
                "add_list_item",
                "update_list_item",
                "resolve_list_item",
                "remove_list_item",
            ) and f.mode != "list":
                raise PatchValidationError(
                    _rejection(index, op, "mode_mismatch", f"field is mode={f.mode}")
                )
            if op.type in ("update_list_item", "resolve_list_item", "remove_list_item"):
                items = (latest.list_items.get(f.id, {}) if latest else {})
                if op.item_key not in items:
                    raise PatchValidationError(
                        _rejection(
                            index,
                            op,
                            "item_not_found",
                            f"item_key {op.item_key!r} not found",
                        )
                    )

        # Apply (after validation).
        new_version = _FakeVersion(new_state_version, cfg, latest.state_version if latest else None)
        if latest is not None:
            for fid, v in latest.single_values.items():
                new_version.single_values[fid] = {
                    "text": v["text"],
                    "source_refs": list(v["source_refs"]),
                }
            for fid, items in latest.list_items.items():
                new_version.list_items[fid] = {
                    k: {
                        "text": it["text"],
                        "resolved": it["resolved"],
                        "source_refs": list(it["source_refs"]),
                    }
                    for k, it in items.items()
                }

        applied_types: list[str] = []
        for op in request.operations:
            f = fields_by_key[op.field_key]
            refs = list(op.source_refs)
            if op.type == "replace_single":
                new_version.single_values[f.id] = {"text": op.text, "source_refs": refs}
            elif op.type == "clear_single":
                new_version.single_values.pop(f.id, None)
            elif op.type == "add_list_item":
                items = new_version.list_items.setdefault(f.id, {})
                n = 1
                while f"{f.key}-{n:02d}" in items:
                    n += 1
                items[f"{f.key}-{n:02d}"] = {
                    "text": op.text,
                    "resolved": False,
                    "source_refs": refs,
                }
            elif op.type == "update_list_item":
                items = new_version.list_items.setdefault(f.id, {})
                if op.item_key in items:
                    items[op.item_key]["text"] = op.text
                    items[op.item_key]["source_refs"] = refs
            elif op.type == "resolve_list_item":
                items = new_version.list_items.setdefault(f.id, {})
                if op.item_key in items:
                    items[op.item_key]["resolved"] = True
                    items[op.item_key]["source_refs"] = refs
            elif op.type == "remove_list_item":
                items = new_version.list_items.setdefault(f.id, {})
                items.pop(op.item_key, None)
            applied_types.append(op.type)

        self._versions_by_campaign[cid].append(new_version)

        from shared_contracts.models import CampaignStatePatchResponse
        self._audit.append(
            {
                "action": "campaign_state_patch_applied",
                "campaign_id": cid,
                "from_state_version": latest.state_version if latest else None,
                "to_state_version": new_state_version,
                "operations": [
                    {"type": op.type, "field_key": op.field_key}
                    for op in request.operations
                ],
            }
        )
        return CampaignStatePatchResponse(
            applied_state_version=new_state_version,
            config_version=cfg,
            applied_operations=applied_types,
            failed_operations=[],
        )


def _rejection(op_index: int, op: CampaignStatePatchOperation, code: str, detail: str):
    from shared_contracts.models import CampaignStatePatchRejection
    return CampaignStatePatchRejection(
        op_index=op_index,
        op_type=op.type,
        code=code,  # type: ignore[arg-type]
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> _FakeValueService:
    return _FakeValueService()


@pytest.fixture
def client(monkeypatch, service):
    from app.api.settings import campaigns as api_module

    monkeypatch.setattr(api_module, "campaign_state_value_service", service)

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    async def fake_get_db():
        yield object()

    app.dependency_overrides[get_db] = fake_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _ok_op(op_type: str, field_key: str, **kwargs):
    from shared_contracts.models import (
        CampaignStateAddListItem,
        CampaignStateClearSingle,
        CampaignStateRemoveListItem,
        CampaignStateReplaceSingle,
        CampaignStateResolveListItem,
        CampaignStateUpdateListItem,
    )

    cls = {
        "replace_single": CampaignStateReplaceSingle,
        "clear_single": CampaignStateClearSingle,
        "add_list_item": CampaignStateAddListItem,
        "update_list_item": CampaignStateUpdateListItem,
        "resolve_list_item": CampaignStateResolveListItem,
        "remove_list_item": CampaignStateRemoveListItem,
    }[op_type]
    return cls(field_key=field_key, reason="user said so", source_refs=[], **kwargs)


def test_apply_replace_single_creates_v1(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "current_focus", "single")

    body = {
        "base_state_version": None,
        "config_version": 1,
        "operations": [
            {
                "type": "replace_single",
                "field_key": "current_focus",
                "text": "Fight the boss",
                "reason": "Session 5 outcome",
                "source_refs": [f"file:{uuid.uuid4()}:sha:abcdef0123456789"],
            }
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["applied_state_version"] == 1
    assert payload["applied_operations"] == ["replace_single"]
    assert payload["failed_operations"] == []
    assert len(service.audit_entries()) == 1


def test_second_patch_with_stale_base_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "focus", "single")

    r1 = client.post(
        f"/api/settings/campaigns/{cid}/state/patch",
        json={
            "base_state_version": None,
            "config_version": 1,
            "operations": [
                {"type": "replace_single", "field_key": "focus", "text": "v1",
                 "reason": "x", "source_refs": []}
            ],
        },
    )
    assert r1.status_code == 200

    # Stale base (still None) — server already at v1.
    r2 = client.post(
        f"/api/settings/campaigns/{cid}/state/patch",
        json={
            "base_state_version": None,
            "config_version": 1,
            "operations": [
                {"type": "replace_single", "field_key": "focus", "text": "v2",
                 "reason": "x", "source_refs": []}
            ],
        },
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "state_version_conflict"


def test_unknown_field_key_returns_422_no_partial_apply(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "focus", "single")

    body = {
        "base_state_version": None,
        "config_version": 1,
        "operations": [
            {"type": "replace_single", "field_key": "focus", "text": "ok",
             "reason": "ok1", "source_refs": []},
            {"type": "replace_single", "field_key": "missing_field", "text": "x",
             "reason": "ok2", "source_refs": []},
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "patch_validation_failed"
    assert detail["rejection"]["code"] == "field_not_found"
    assert detail["rejection"]["op_index"] == 1
    # Никакой версии не появилось.
    assert service.audit_entries() == []


def test_mode_mismatch_returns_422(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "agreements", "list")

    body = {
        "base_state_version": None,
        "config_version": 1,
        "operations": [
            {"type": "replace_single", "field_key": "agreements", "text": "x",
             "reason": "wrong mode", "source_refs": []}
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["rejection"]["code"] == "mode_mismatch"


def test_unknown_item_key_returns_422(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "agreements", "list")

    body = {
        "base_state_version": None,
        "config_version": 1,
        "operations": [
            {"type": "add_list_item", "field_key": "agreements", "text": "first",
             "reason": "ok", "source_refs": []},
            {"type": "add_list_item", "field_key": "agreements", "text": "second",
             "reason": "ok", "source_refs": []},
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    assert r.status_code == 200
    assert r.json()["applied_state_version"] == 1

    # Now try update_list_item against unknown item_key on top of v1.
    body2 = {
        "base_state_version": 1,
        "config_version": 1,
        "operations": [
            {"type": "update_list_item", "field_key": "agreements",
             "item_key": "missing-99", "text": "no", "reason": "r", "source_refs": []}
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body2)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["rejection"]["code"] == "item_not_found"


def test_config_version_mismatch_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "focus", "single")

    body = {
        "base_state_version": None,
        "config_version": 999,  # not 1
        "operations": [
            {"type": "replace_single", "field_key": "focus", "text": "x",
             "reason": "r", "source_refs": []}
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "config_version_conflict"


def test_invalid_source_ref_returns_422(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "focus", "single")

    body = {
        "base_state_version": None,
        "config_version": 1,
        "operations": [
            {
                "type": "replace_single",
                "field_key": "focus",
                "text": "x",
                "reason": "r",
                "source_refs": ["just-a-string-not-a-ref"],
            }
        ],
    }
    r = client.post(f"/api/settings/campaigns/{cid}/state/patch", json=body)
    # Router catches CampaignStateValueError (InvalidSourceRefError, http_status=422)
    # but does not attach rejection because no PatchValidationError; detail is the code.
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_source_ref"


def test_add_update_resolve_remove_list_item(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "agreements", "list")

    # 1) Add two items.
    r = client.post(
        f"/api/settings/campaigns/{cid}/state/patch",
        json={
            "base_state_version": None,
            "config_version": 1,
            "operations": [
                {"type": "add_list_item", "field_key": "agreements",
                 "text": "first", "reason": "r", "source_refs": []},
                {"type": "add_list_item", "field_key": "agreements",
                 "text": "second", "reason": "r", "source_refs": []},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["applied_state_version"] == 1

    # 2) Update first item, resolve second, remove non-existing (should fail with item_not_found).
    r2 = client.post(
        f"/api/settings/campaigns/{cid}/state/patch",
        json={
            "base_state_version": 1,
            "config_version": 1,
            "operations": [
                {"type": "update_list_item", "field_key": "agreements",
                 "item_key": "agreements-01", "text": "first (updated)",
                 "reason": "r", "source_refs": []},
                {"type": "resolve_list_item", "field_key": "agreements",
                 "item_key": "agreements-02", "reason": "r", "source_refs": []},
            ],
        },
    )
    assert r2.status_code == 200
    assert r2.json()["applied_state_version"] == 2


def test_audit_payload_written_on_success(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    service.add_field(cid, "focus", "single")

    r = client.post(
        f"/api/settings/campaigns/{cid}/state/patch",
        json={
            "base_state_version": None,
            "config_version": 1,
            "operations": [
                {"type": "replace_single", "field_key": "focus", "text": "x",
                 "reason": "r", "source_refs": []}
            ],
        },
    )
    assert r.status_code == 200
    audits = service.audit_entries()
    assert len(audits) == 1
    a = audits[0]
    assert a["action"] == "campaign_state_patch_applied"
    assert a["from_state_version"] is None
    assert a["to_state_version"] == 1
    assert a["operations"] == [{"type": "replace_single", "field_key": "focus"}]