from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.config import AppConfig
from app.config_loader import get_config
from app.domains.registry import DomainRegistry


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["config"])


class DomainInfo(BaseModel):
    domain_id: str
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


def _get_domain_registry(request: Request) -> DomainRegistry:
    registry = getattr(request.app.state, "domain_registry", None)
    if isinstance(registry, DomainRegistry):
        return registry
    registry = DomainRegistry()
    registry.load()
    return registry


@router.get("/domains", response_model=DomainsResponse)
async def list_domains(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> DomainsResponse:
    """
    Возвращает список доменов. Источники:
    - config.vaults (vault-привязанные домены)
    - DomainRegistry (промпты могут быть у доменов без vault)
    
    Поле vault_enabled=True означает "есть хотя бы один enabled vault в домене".
    """
    registry = _get_domain_registry(request)
    
    domain_map: dict[str, DomainInfo] = {}
    
    # 1. Домены из registry (prompts.yaml)
    for domain_id in registry.domain_ids():
        domain_map[domain_id] = DomainInfo(
            domain_id=domain_id,
            has_vault=False,
            vault_enabled=False,
        )
    
    # 2. Домены из vaults конфига
    for vault in config.vaults.values():
        existing = domain_map.get(vault.domain_id)
        if existing is None:
            domain_map[vault.domain_id] = DomainInfo(
                domain_id=vault.domain_id,
                has_vault=True,
                vault_enabled=vault.enabled,
            )
        else:
            existing.has_vault = True
            if vault.enabled:
                existing.vault_enabled = True
    
    # Приоритет сортировки
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
    config: AppConfig = Depends(get_config),
) -> VaultsResponse:
    """Возвращает список vault'ов с опциональной фильтрацией."""
    vaults = []
    search_lower = search.lower() if search else None
    
    for vault in config.vaults.values():
        if domain_id is not None and vault.domain_id != domain_id:
            continue
        if search_lower is not None and search_lower not in vault.vault_id.lower():
            continue
        vaults.append(
            VaultInfo(
                vault_id=vault.vault_id,
                domain_id=vault.domain_id,
                enabled=vault.enabled,
            )
        )
    
    vaults.sort(key=lambda v: (v.domain_id, v.vault_id))
    return VaultsResponse(vaults=vaults)