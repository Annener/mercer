from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Domain, Vault
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


class DomainInfo(BaseModel):
    domain_id: str
    display_name: str = ""          # ← ДОБАВЛЕНО
    description: str | None = None  # ← ДОБАВЛЕНО
    has_vault: bool = False
    vault_enabled: bool = False


class DomainsResponse(BaseModel):
    domains: list[DomainInfo]


class VaultInfo(BaseModel):
    vault_id: str
    domain_id: str
    enabled: bool


class VaultsResponse(BaseModel):
    vaults: list[VaultInfo]


@router.get("/domains", response_model=DomainsResponse)
async def list_domains(
    db: AsyncSession = Depends(get_db),
) -> DomainsResponse:
    domain_map: dict[str, DomainInfo] = {}

    # Сначала загружаем все enabled домены с display_name
    domains_result = await db.execute(
        select(Domain).where(Domain.enabled == True).order_by(Domain.domain_id)
    )
    for domain in domains_result.scalars().all():
        domain_map[domain.domain_id] = DomainInfo(
            domain_id=domain.domain_id,
            display_name=domain.display_name,
            description=domain.description,
            has_vault=False,
            vault_enabled=False,
        )

    # Подтягиваем информацию о vault'ах
    vaults_result = await db.execute(select(Vault))
    for vault in vaults_result.scalars().all():
        existing = domain_map.get(vault.domain_id)
        if existing is None:
            # Домен отключён или отсутствует — создаём запись с display_name = domain_id
            domain_map[vault.domain_id] = DomainInfo(
                domain_id=vault.domain_id,
                display_name=vault.domain_id,
                description=None,
                has_vault=True,
                vault_enabled=vault.enabled,
            )
            continue
        existing.has_vault = True
        if vault.enabled:
            existing.vault_enabled = True

    priority = {"dnd": 0, "work": 1, "default": 99}
    domains = sorted(
        domain_map.values(),
        key=lambda d: (priority.get(d.domain_id, 50), d.domain_id),
    )
    return DomainsResponse(domains=domains)


@router.get("/vaults", response_model=VaultsResponse)
async def list_vaults(
    domain_id: str | None = Query(default=None, description="Фильтр по домену"),
    search: str | None = Query(default=None, description="Поиск по имени vault"),
    db: AsyncSession = Depends(get_db),
) -> VaultsResponse:
    stmt = select(Vault)
    if domain_id is not None:
        stmt = stmt.where(Vault.domain_id == domain_id)
    if search:
        stmt = stmt.where(Vault.vault_id.ilike(f"%{search}%"))
    result = await db.execute(stmt.order_by(Vault.domain_id, Vault.vault_id))
    return VaultsResponse(
        vaults=[
            VaultInfo(
                vault_id=vault.vault_id,
                domain_id=vault.domain_id,
                enabled=vault.enabled,
            )
            for vault in result.scalars().all()
        ]
    )