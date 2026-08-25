"""Tests for Campaign State field configuration API (Stage 1).

Strategy: monkeypatch the service singleton so the route handlers use an
in-memory store. This mirrors the pattern from test_update_mode_api.py and
keeps tests fast and DB-free.
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Any

import pytest
from app.api.settings.campaigns import router
from app.db.models import CampaignStateFieldConfig
from app.db.session import get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from shared_contracts.models import CampaignStateFieldConfigRead

# ---------------------------------------------------------------------------
# In-memory fake DB session and service
# ---------------------------------------------------------------------------


class _FakeQueryResult:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> _FakeQueryResult:
        return self

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeCampaign:
    """Достаточно Campaign-объекта для _campaign_with_tags/get_campaign."""

    def __init__(self, campaign_id: str) -> None:
        self.id = uuid.UUID(campaign_id)


class FakeSession:
    """Минимальный AsyncSession-стаб: поддерживает get() и execute().

    Только то, что нужно сервису: db.get(Campaign, ...), db.execute(select(...)).
    """

    def __init__(self, campaigns: dict[str, _FakeCampaign], fields: dict[str, CampaignStateFieldConfig]) -> None:
        self._campaigns = campaigns
        self._fields = fields

    async def get(self, model: Any, pk: Any) -> Any:
        if model is CampaignStateFieldConfig:
            row = self._fields.get(str(pk))
            return row
        # Campaign — используем стаб.
        row = self._campaigns.get(str(pk))
        return row

    async def execute(self, stmt: Any) -> _FakeQueryResult:
        # Поддерживаем только select() со сравнениями .where(CampaignStateFieldConfig.campaign_id == X)
        # и select(...).where(CampaignStateFieldConfig.id == fid, ...).
        stmt.compile(dialect=type("D", (), {"statement_compiler": type("C", (), {"visit_select": lambda self, *a, **k: None})()})())
        # Проще — извлечь campaign_id из where-clauses через атрибуты stmt.whereclause.
        where = getattr(stmt, "whereclause", None)
        # Fallback: фильтруем все поля по campaign_id, найденному в where.
        # Упрощённо: пройдём по всем полям и применим фильтр вручную.
        candidates = list(self._fields.values())
        target_campaign_id: str | None = None
        target_field_id: str | None = None

        # Используем приватный API stmt: _whereclause / whereclause.
        with contextlib.suppress(Exception):  # best-effort in fake DB
            list(getattr(stmt, "_whereclause", None) or [where]) if where else []

        # Самый надёжный путь — обойти атрибуты stmt через извлечение right-hand-side
        # из whereclause. SQLAlchemy позволяет получить .right у ColumnOperators.
        def _extract(obj: Any) -> Any:
            if obj is None:
                return None
            # BinaryExpression: .left / .right
            right = getattr(obj, "right", None)
            left = getattr(obj, "left", None)
            if right is not None and not isinstance(right, (type, type(None))):
                return right
            if left is not None and not isinstance(left, (type, type(None))):
                return _extract(left)
            return None

        with contextlib.suppress(Exception):  # best-effort filter extraction in fake DB
            rhs = _extract(where)
            if rhs is not None and hasattr(rhs, "value"):
                val = rhs.value
                if isinstance(val, uuid.UUID):
                    # Если ищем по campaign_id, то поля фильтруются; если по id — то одна строка.
                    # Проверим имя колонки слева от whereclause.
                    left = getattr(where, "left", None)
                    getattr(getattr(left, "key", None), "__hash__", None)
                    # Надёжнее: получим ключ через .key у Column:
                    with contextlib.suppress(Exception):  # attribute introspection
                        getattr(left, "table", None)
                        left_name = getattr(left, "name", None) or getattr(left, "key", None)
                    if "left_name" not in locals() or left_name is None:
                        left_name = None  # explicit fallback to keep mypy quiet
                    if left_name == "campaign_id":
                        target_campaign_id = str(val)
                    elif left_name == "id":
                        target_field_id = str(val)

        if target_field_id is not None:
            row = self._fields.get(target_field_id)
            return _FakeQueryResult([row] if row else [])

        if target_campaign_id is not None:
            rows = [r for r in candidates if str(r.campaign_id) == target_campaign_id]
            return _FakeQueryResult(rows)

        return _FakeQueryResult(candidates)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def refresh(self, obj: Any, attribute_names: list[str] | None = None) -> None:
        return None


class _FakeService:
    """Поведенческий дублёр CampaignStateFieldService для тестов."""

    def __init__(self) -> None:
        self._fields: dict[str, CampaignStateFieldConfig] = {}
        self._campaigns: dict[str, _FakeCampaign] = {}

    def register_campaign(self, campaign_id: str) -> None:
        self._campaigns[campaign_id] = _FakeCampaign(campaign_id)

    async def list_fields(self, db: AsyncSession, campaign_id: uuid.UUID) -> list[CampaignStateFieldConfigRead]:
        if str(campaign_id) not in self._campaigns:
            from app.services.campaign_state_service import CampaignNotFoundError
            raise CampaignNotFoundError(str(campaign_id))
        rows = sorted(
            [r for r in self._fields.values() if str(r.campaign_id) == str(campaign_id)],
            key=lambda r: (r.display_order, r.key),
        )
        return [_to_read(r) for r in rows]

    async def create_field(self, db: AsyncSession, campaign_id: uuid.UUID, payload) -> CampaignStateFieldConfigRead:
        from app.services.campaign_state_service import (
            CampaignNotFoundError,
            CampaignStateFieldError,
            FieldKeyDuplicateError,
            InvalidFieldKeyError,
        )
        if str(campaign_id) not in self._campaigns:
            raise CampaignNotFoundError(str(campaign_id))
        if not _FIELD_KEY_RE.match(payload.key):
            raise InvalidFieldKeyError("field key invalid")
        if any(str(r.campaign_id) == str(campaign_id) and r.key == payload.key for r in self._fields.values()):
            raise FieldKeyDuplicateError("dup")
        if payload.mode not in _ALLOWED_MODES:
            raise CampaignStateFieldError("mode invalid")
        row = CampaignStateFieldConfig(
            id=uuid.uuid4(),
            campaign_id=campaign_id,
            key=payload.key,
            label=payload.label,
            description=payload.description,
            mode=payload.mode,
            enabled=payload.enabled,
            display_order=payload.display_order,
            created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            updated_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        self._fields[str(row.id)] = row
        return _to_read(row)

    async def update_field(self, db: AsyncSession, campaign_id: uuid.UUID, field_id: uuid.UUID, payload) -> CampaignStateFieldConfigRead:
        from app.services.campaign_state_service import (
            FieldKeyImmutableError,
            FieldModeImmutableError,
            FieldNotFoundError,
        )
        row = self._fields.get(str(field_id))
        if row is None or str(row.campaign_id) != str(campaign_id):
            raise FieldNotFoundError(str(field_id))
        if "key" in payload.model_fields_set and payload.key is not None:
            raise FieldKeyImmutableError("key immutable")
        if "mode" in payload.model_fields_set and payload.mode is not None:
            raise FieldModeImmutableError("mode immutable")
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(row, k, v)
        return _to_read(row)

    async def delete_field(self, db: AsyncSession, campaign_id: uuid.UUID, field_id: uuid.UUID) -> None:
        from app.services.campaign_state_service import FieldNotFoundError
        row = self._fields.get(str(field_id))
        if row is None or str(row.campaign_id) != str(campaign_id):
            raise FieldNotFoundError(str(field_id))
        del self._fields[str(field_id)]

    async def reorder_fields(self, db: AsyncSession, campaign_id: uuid.UUID, ordered_field_ids: list[str]):
        from app.services.campaign_state_service import (
            CampaignNotFoundError,
            InvalidReorderPayloadError,
        )
        if str(campaign_id) not in self._campaigns:
            raise CampaignNotFoundError(str(campaign_id))
        try:
            parsed = [uuid.UUID(fid) for fid in ordered_field_ids]
        except ValueError as exc:
            raise InvalidReorderPayloadError(str(exc))
        if len(parsed) != len(set(parsed)):
            raise InvalidReorderPayloadError("duplicates")
        rows = [r for r in self._fields.values() if str(r.campaign_id) == str(campaign_id)]
        existing = {str(r.id) for r in rows}
        requested = {str(p) for p in parsed}
        if existing != requested:
            raise InvalidReorderPayloadError("coverage mismatch")
        for index, fid in enumerate(parsed):
            self._fields[str(fid)].display_order = index
        return await self.list_fields(db, campaign_id)


# Re-export service-layer constants used by the fake.
from app.services.campaign_state_service import (
    _ALLOWED_MODES,
    _FIELD_KEY_RE,
)


def _to_read(row: CampaignStateFieldConfig) -> CampaignStateFieldConfigRead:
    return CampaignStateFieldConfigRead(
        id=str(row.id),
        field_id=str(row.id),
        campaign_id=str(row.campaign_id),
        key=row.key,
        label=row.label,
        description=row.description,
        mode=row.mode,
        enabled=row.enabled,
        display_order=row.display_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> _FakeService:
    return _FakeService()


@pytest.fixture
def client(monkeypatch, service: _FakeService):
    # Подменяем ссылку на сервис в модуле роутера: endpoint импортирует
    # `campaign_state_field_service` локально, поэтому патчить надо там,
    # где его используют, а не только в исходном модуле сервиса.
    from app.api.settings import campaigns as campaigns_module
    monkeypatch.setattr(campaigns_module, "campaign_state_field_service", service)

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")

    fake_db = FakeSession(campaigns=service._campaigns, fields=service._fields)

    async def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = fake_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_empty(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)

    resp = client.get(f"/api/settings/campaigns/{cid}/state-fields")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_list_update_delete_reorder(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)

    # Create #1
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "current_focus", "label": "Текущий фокус", "mode": "single", "display_order": 0},
    )
    assert r.status_code == 201, r.text
    f1 = r.json()
    assert f1["key"] == "current_focus"
    assert f1["mode"] == "single"
    assert f1["enabled"] is True
    # Регресс-тест: в ответе должны быть ОБА — id и field_id (алиас).
    # Старые клиенты (фронт) читают f.field_id; без алиаса они получают undefined,
    # кнопки (toggleEnabled, remove) молча игнорируются — поле не удаляется.
    assert f1.get("field_id") == f1["id"], (
        "field_id alias missing: клиент не сможет удалить/обновить поле"
    )

    # Create #2
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={
            "key": "agreements",
            "label": "Договорённости",
            "description": "Список",
            "mode": "list",
            "display_order": 1,
            "enabled": False,
        },
    )
    assert r.status_code == 201, r.text
    f2 = r.json()

    # List (ordered by display_order)
    r = client.get(f"/api/settings/campaigns/{cid}/state-fields")
    assert r.status_code == 200
    items = r.json()
    assert [i["key"] for i in items] == ["current_focus", "agreements"]

    # Partial update (exclude_unset semantics): только label
    r = client.put(
        f"/api/settings/campaigns/{cid}/state-fields/{f1['id']}",
        json={"label": "Новый фокус"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Новый фокус"
    # mode не менялся
    assert r.json()["mode"] == "single"

    # Reorder: меняем порядок
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields/reorder",
        json={"field_ids": [f2["id"], f1["id"]]},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["key"] for i in items] == ["agreements", "current_focus"]
    assert items[0]["display_order"] == 0
    assert items[1]["display_order"] == 1

    # Delete
    r = client.delete(f"/api/settings/campaigns/{cid}/state-fields/{f2['id']}")
    assert r.status_code == 204

    r = client.get(f"/api/settings/campaigns/{cid}/state-fields")
    assert r.status_code == 200
    assert [i["key"] for i in r.json()] == ["current_focus"]


def test_invalid_field_key_returns_422(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "1BadKey", "label": "X", "mode": "single"},
    )
    # 422 от FastAPI на валидации Pydantic (max_length/regex не зашит в схему — regex
    # проверяется в сервисе, тогда 422 invalid_field_key).
    # Здесь полагаемся на сервисный regex.
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_field_key"


def test_key_duplicate_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    body = {"key": "agreements", "label": "A", "mode": "list"}
    assert client.post(f"/api/settings/campaigns/{cid}/state-fields", json=body).status_code == 201
    r = client.post(f"/api/settings/campaigns/{cid}/state-fields", json=body)
    assert r.status_code == 409
    assert r.json()["detail"] == "field_key_duplicate"


def test_key_immutable_on_update_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "agreements", "label": "A", "mode": "list"},
    ).json()
    r = client.put(
        f"/api/settings/campaigns/{cid}/state-fields/{f['id']}",
        json={"key": "renamed", "label": "A"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "field_key_immutable"


def test_mode_immutable_on_update_returns_409(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "agreements", "label": "A", "mode": "list"},
    ).json()
    r = client.put(
        f"/api/settings/campaigns/{cid}/state-fields/{f['id']}",
        json={"mode": "single", "label": "A"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "field_mode_immutable"


def test_reorder_coverage_mismatch_returns_422(client, service):
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    f = client.post(
        f"/api/settings/campaigns/{cid}/state-fields",
        json={"key": "agreements", "label": "A", "mode": "list"},
    ).json()
    # Ожидаем два ID — отдаём только один
    r = client.post(
        f"/api/settings/campaigns/{cid}/state-fields/reorder",
        json={"field_ids": [f["id"], str(uuid.uuid4())]},
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_reorder_payload"


def test_campaign_not_found_returns_404(client):
    missing = str(uuid.uuid4())
    r = client.get(f"/api/settings/campaigns/{missing}/state-fields")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Регресс-тесты на 400 для невалидного UUID (баг #2)
# ---------------------------------------------------------------------------


def test_delete_field_with_invalid_field_id_returns_400(client, service):
    """DELETE с невалидным field_id → 400 (раньше падало 500 на uuid.UUID())."""
    cid = str(uuid.uuid4())
    service.register_campaign(cid)
    bad_ids = [
        "not-a-uuid",
        "12345",
        "abc-def",
        "00000000-0000-0000-0000-zzzzzzzzzzzz",
    ]
    for bad in bad_ids:
        r = client.delete(
            f"/api/settings/campaigns/{cid}/state-fields/{bad}",
        )
        assert r.status_code == 400, (
            f"expected 400 for bad field_id={bad!r}, got {r.status_code}: {r.text}"
        )
        assert r.json()["detail"] == "invalid_field_id"


def test_delete_field_with_invalid_campaign_id_returns_400(client):
    """DELETE с невалидным campaign_id → 400 (а не 500)."""
    bad = "not-a-uuid"
    r = client.delete(
        f"/api/settings/campaigns/{bad}/state-fields/{uuid.uuid4()}",
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_campaign_id"
