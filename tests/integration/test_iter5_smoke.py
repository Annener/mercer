"""
Integration smoke-tests — Iteration 5
======================================
Проверяет все ключевые инварианты после рефакторинга iter1-4:

  1. Domain → Vault → Document/Tag → Campaign — базовая CRUD-цепочка
  2. Теги принадлежат домену (не vault)
  3. Кампании принадлежат домену (не vault)
  4. Retrieval: пустые теги кампании → document_ids = []
  5. Retrieval: теги кампании → только документы этой кампании
  6. Pipeline: campaign_id nullable (общий и кампанийный)
  7. PipelineContext: domain_id + vault_ids работают вместе
  8. CreateChatRequest: back-compat vault_id + новый domain_id

ЗАПУСК:
-------
  # из корня репозитория (rag-backend)
  cd rag-backend

  # 1. Поднять только нужные сервисы (без LLM)
  docker compose up -d postgres

  # 2. Применить миграции
  docker compose run --rm rag-backend alembic upgrade head

  # 3. Запустить тесты
  docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://... rag-backend \\
      pytest tests/integration/test_iter5_smoke.py -v

  Или локально с виртуальным окружением:
  DATABASE_URL=postgresql+asyncpg://mercer:mercer@localhost:5432/mercer \\
      pytest tests/integration/test_iter5_smoke.py -v

ЗАВИСИМОСТИ:
------------
  pip install pytest pytest-asyncio sqlalchemy[asyncio] asyncpg
  (все уже есть в requirements.txt rag-backend)

ПРИМЕЧАНИЕ:
-----------
  Тесты создают собственную транзакцию и откатывают её после каждого теста.
  Никаких данных в БД не остаётся.
"""
from __future__ import annotations

import uuid
import os
import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

# ── модели БД ──
from app.db.models import Domain, Vault, Tag, Campaign, Document, DocumentLabel, Pipeline

# ── retrieval helpers ──
from app.services.retrieval import get_allowed_tag_ids, get_document_ids_by_tags

# ── shared_contracts ──
from shared_contracts.models import (
    TagCreate,
    TagRead,
    CampaignCreate,
    CampaignRead,
    PipelineCreate,
    PipelineRead,
    PipelineContext,
    PipelineStep,
    FinalComposition,
    CreateChatRequest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://mercer:mercer@localhost:5432/mercer",
)


@pytest_asyncio.fixture(scope="session")
async def engine():
    e = create_async_engine(DATABASE_URL, echo=False)
    yield e
    await e.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Каждый тест получает сессию в транзакции, которая откатывается после теста."""
    async with engine.begin() as conn:
        session = AsyncSession(bind=conn)
        yield session
        await session.close()
        await conn.rollback()


@pytest_asyncio.fixture
async def domain(db: AsyncSession):
    """Создаёт тестовый домен."""
    d = Domain(
        domain_id=f"test-domain-{uuid.uuid4().hex[:8]}",
        display_name="Test Domain",
        is_system=False,
        enabled=True,
    )
    db.add(d)
    await db.flush()
    return d


@pytest_asyncio.fixture
async def vault(db: AsyncSession, domain: Domain):
    """Создаёт Vault, привязанный к тестовому домену."""
    v = Vault(
        vault_id=f"test-vault-{uuid.uuid4().hex[:8]}",
        domain_id=domain.domain_id,
        display_name="Test Vault",
        enabled=True,
        binding_status="unbound",
    )
    db.add(v)
    await db.flush()
    return v


# ---------------------------------------------------------------------------
# 1. Тег принадлежит домену, не vault
# ---------------------------------------------------------------------------

class TestTagBelongsToDomain:
    async def test_tag_create_schema_has_domain_id(self):
        """TagCreate.domain_id существует, vault_id отсутствует."""
        fields = set(TagCreate.model_fields.keys())
        assert "domain_id" in fields, "TagCreate должен иметь domain_id"
        assert "vault_id" not in fields, "TagCreate не должен содержать vault_id"

    async def test_tag_read_schema_has_domain_id(self):
        """TagRead.domain_id существует, vault_id отсутствует."""
        fields = set(TagRead.model_fields.keys())
        assert "domain_id" in fields
        assert "vault_id" not in fields

    async def test_tag_orm_has_domain_id(self, db: AsyncSession, domain: Domain):
        """ORM-модель Tag имеет domain_id, сохраняется без vault_id."""
        tag = Tag(
            name="test-tag",
            domain_id=uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id,
            campaign_id=None,
        )
        db.add(tag)
        await db.flush()
        await db.refresh(tag)
        assert str(tag.domain_id) == domain.domain_id
        assert not hasattr(tag, "vault_id") or tag.vault_id is None


# ---------------------------------------------------------------------------
# 2. Кампания принадлежит домену, не vault
# ---------------------------------------------------------------------------

class TestCampaignBelongsToDomain:
    async def test_campaign_create_schema_has_domain_id(self):
        fields = set(CampaignCreate.model_fields.keys())
        assert "domain_id" in fields
        assert "vault_id" not in fields

    async def test_campaign_read_schema_has_domain_id(self):
        fields = set(CampaignRead.model_fields.keys())
        assert "domain_id" in fields
        assert "vault_id" not in fields

    async def test_campaign_orm_domain_id(self, db: AsyncSession, domain: Domain):
        camp = Campaign(
            name="Test Campaign",
            domain_id=uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id,
        )
        db.add(camp)
        await db.flush()
        await db.refresh(camp)
        assert str(camp.domain_id) == domain.domain_id


# ---------------------------------------------------------------------------
# 3. get_allowed_tag_ids — пустая кампания
# ---------------------------------------------------------------------------

class TestGetAllowedTagIds:
    async def test_empty_campaign_returns_empty_set(
        self, db: AsyncSession, domain: Domain
    ):
        """
        Кампания без тегов → get_allowed_tag_ids возвращает пустое множество.
        Это гарантирует: retrieval НЕ будет запущен по всему домену.
        """
        camp = Campaign(
            name="Empty Campaign",
            domain_id=uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id,
        )
        db.add(camp)
        await db.flush()

        result = await get_allowed_tag_ids(
            domain_id=domain.domain_id,
            campaign_id=str(camp.id),
            db=db,
        )
        assert result == set(), (
            "Пустая кампания должна возвращать пустое множество тегов, "
            "а не теги всего домена."
        )

    async def test_global_tags_included_for_campaign(
        self, db: AsyncSession, domain: Domain
    ):
        """
        Глобальный тег домена (campaign_id=None) виден в кампании.
        """
        domain_uuid = uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id
        global_tag = Tag(name="global", domain_id=domain_uuid, campaign_id=None)
        db.add(global_tag)
        camp = Campaign(name="Camp With Global", domain_id=domain_uuid)
        db.add(camp)
        await db.flush()

        result = await get_allowed_tag_ids(
            domain_id=domain.domain_id,
            campaign_id=str(camp.id),
            db=db,
        )
        assert str(global_tag.id) in result

    async def test_campaign_tag_not_visible_in_other_campaign(
        self, db: AsyncSession, domain: Domain
    ):
        """
        Тег одной кампании не виден в другой кампании.
        """
        domain_uuid = uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id
        camp_a = Campaign(name="Camp A", domain_id=domain_uuid)
        camp_b = Campaign(name="Camp B", domain_id=domain_uuid)
        db.add_all([camp_a, camp_b])
        await db.flush()

        tag_a = Tag(name="tag-a", domain_id=domain_uuid, campaign_id=camp_a.id)
        db.add(tag_a)
        await db.flush()

        result_b = await get_allowed_tag_ids(
            domain_id=domain.domain_id,
            campaign_id=str(camp_b.id),
            db=db,
        )
        assert str(tag_a.id) not in result_b, (
            "Тег кампании A не должен быть виден в кампании B."
        )


# ---------------------------------------------------------------------------
# 4. get_document_ids_by_tags — пустой список тегов → []
# ---------------------------------------------------------------------------

class TestGetDocumentIdsByTags:
    async def test_empty_tag_ids_returns_empty_list(
        self, db: AsyncSession, domain: Domain
    ):
        """
        Инвариант: пустой tag_ids → [] (не запрос по всему домену).
        """
        result = await get_document_ids_by_tags(
            tag_ids=[],
            domain_id=domain.domain_id,
            db=db,
        )
        assert result == []

    async def test_tagged_document_found(
        self, db: AsyncSession, domain: Domain, vault: Vault
    ):
        """
        Документ с тегом находится через get_document_ids_by_tags.
        """
        domain_uuid = uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id
        tag = Tag(name="findme", domain_id=domain_uuid, campaign_id=None)
        db.add(tag)

        doc = Document(
            vault_id=vault.vault_id,
            source_path="/test/doc.pdf",
            md5="abc123",
            mtime=0,
            status="indexed",
        )
        db.add(doc)
        await db.flush()

        label = DocumentLabel(document_id=doc.id, tag_id=tag.id)
        db.add(label)
        await db.flush()

        result = await get_document_ids_by_tags(
            tag_ids=[str(tag.id)],
            domain_id=domain.domain_id,
            db=db,
        )
        assert str(doc.id) in result

    async def test_document_from_other_domain_not_found(
        self, db: AsyncSession, domain: Domain, vault: Vault
    ):
        """
        Документ из другого домена не попадает в результат.
        """
        # Второй домен и vault
        other_domain = Domain(
            domain_id=f"other-{uuid.uuid4().hex[:8]}",
            display_name="Other Domain",
        )
        db.add(other_domain)
        await db.flush()

        other_vault = Vault(
            vault_id=f"other-vault-{uuid.uuid4().hex[:8]}",
            domain_id=other_domain.domain_id,
            enabled=True,
            binding_status="unbound",
        )
        db.add(other_vault)

        other_domain_uuid = uuid.UUID(other_domain.domain_id) if len(other_domain.domain_id) == 36 else other_domain.domain_id
        other_tag = Tag(name="cross-domain", domain_id=other_domain_uuid, campaign_id=None)
        db.add(other_tag)

        other_doc = Document(
            vault_id=other_vault.vault_id,
            source_path="/other/doc.pdf",
            md5="def456",
            mtime=0,
            status="indexed",
        )
        db.add(other_doc)
        await db.flush()

        other_label = DocumentLabel(document_id=other_doc.id, tag_id=other_tag.id)
        db.add(other_label)
        await db.flush()

        # Ищем в нашем домене по тегу другого домена → пусто
        result = await get_document_ids_by_tags(
            tag_ids=[str(other_tag.id)],
            domain_id=domain.domain_id,  # наш домен
            db=db,
        )
        assert str(other_doc.id) not in result


# ---------------------------------------------------------------------------
# 5. Pipeline: campaign_id nullable
# ---------------------------------------------------------------------------

class TestPipelineCampaignId:
    def test_pipeline_create_schema_has_campaign_id(self):
        """PipelineCreate.campaign_id существует и nullable."""
        fields = PipelineCreate.model_fields
        assert "campaign_id" in fields
        # default None
        p = PipelineCreate(
            pipeline_id="test",
            domain_id="test-domain",
            name="Test",
            steps=[PipelineStep(
                order=0, type="final", name="Final",
                system_prompt="Answer: {query}",
                is_final=True,
            )],
            final_composition=FinalComposition(system_prompt="s"),
        )
        assert p.campaign_id is None

    def test_pipeline_create_with_campaign_id(self):
        """PipelineCreate принимает campaign_id."""
        cid = str(uuid.uuid4())
        p = PipelineCreate(
            pipeline_id="camp-pipeline",
            domain_id="test-domain",
            campaign_id=cid,
            name="Campaign Pipeline",
            steps=[PipelineStep(
                order=0, type="final", name="Final",
                system_prompt="s",
                is_final=True,
            )],
            final_composition=FinalComposition(system_prompt="s"),
        )
        assert p.campaign_id == cid


# ---------------------------------------------------------------------------
# 6. PipelineContext: domain_id + vault_ids
# ---------------------------------------------------------------------------

class TestPipelineContext:
    def test_pipeline_context_domain_id_required(self):
        """PipelineContext требует domain_id."""
        ctx = PipelineContext(
            query="test",
            domain_id="my-domain",
            vault_ids=["v1", "v2"],
        )
        assert ctx.domain_id == "my-domain"
        assert ctx.vault_ids == ["v1", "v2"]

    def test_pipeline_context_vault_id_backcompat(self):
        """PipelineContext сохраняет back-compat vault_id."""
        ctx = PipelineContext(
            query="test",
            domain_id="my-domain",
            vault_id="old-vault",  # deprecated
        )
        assert ctx.vault_id == "old-vault"
        assert ctx.vault_ids == []

    def test_pipeline_context_vault_ids_default_empty(self):
        """vault_ids по умолчанию пустой список."""
        ctx = PipelineContext(query="q", domain_id="d")
        assert ctx.vault_ids == []


# ---------------------------------------------------------------------------
# 7. CreateChatRequest: back-compat
# ---------------------------------------------------------------------------

class TestCreateChatRequest:
    def test_domain_id_primary(self):
        req = CreateChatRequest(domain_id="my-domain")
        assert req.domain_id == "my-domain"
        assert req.vault_id is None

    def test_vault_id_backcompat(self):
        """Старые клиенты передают только vault_id."""
        req = CreateChatRequest(vault_id="old-vault")
        assert req.vault_id == "old-vault"
        assert req.domain_id is None

    def test_both_fields_accepted(self):
        """Переходный период: оба поля одновременно."""
        req = CreateChatRequest(domain_id="d", vault_id="v")
        assert req.domain_id == "d"
        assert req.vault_id == "v"


# ---------------------------------------------------------------------------
# 8. Disabled vault не участвует в retrieval
# ---------------------------------------------------------------------------

class TestDisabledVaultExcluded:
    async def test_disabled_vault_docs_not_found(
        self, db: AsyncSession, domain: Domain
    ):
        """
        Документы из disabled vault не должны появляться в get_document_ids_by_tags.
        """
        domain_uuid = uuid.UUID(domain.domain_id) if len(domain.domain_id) == 36 else domain.domain_id

        disabled_vault = Vault(
            vault_id=f"disabled-{uuid.uuid4().hex[:8]}",
            domain_id=domain.domain_id,
            enabled=False,  # <— выключен
            binding_status="unbound",
        )
        db.add(disabled_vault)

        tag = Tag(name="disabled-tag", domain_id=domain_uuid, campaign_id=None)
        db.add(tag)

        doc = Document(
            vault_id=disabled_vault.vault_id,
            source_path="/disabled/doc.pdf",
            md5="aaa",
            mtime=0,
            status="indexed",
        )
        db.add(doc)
        await db.flush()

        label = DocumentLabel(document_id=doc.id, tag_id=tag.id)
        db.add(label)
        await db.flush()

        result = await get_document_ids_by_tags(
            tag_ids=[str(tag.id)],
            domain_id=domain.domain_id,
            db=db,
        )
        assert str(doc.id) not in result, (
            "Документ из disabled vault не должен попадать в retrieval."
        )
