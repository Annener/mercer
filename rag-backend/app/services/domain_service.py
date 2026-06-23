from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ClarificationState, Domain, DomainClarificationField, DomainPrompt, Vault
from app.db.utils import transactional


@dataclass(frozen=True)
class DomainConfig:
    domain_id: str
    display_name: str
    enabled: bool
    prompts: dict[str, str]
    clarification_fields: list[dict[str, Any]]


class DomainService:
    def __init__(self) -> None:
        self._cache: dict[str, DomainConfig] = {}

    async def get_domain(self, domain_id: str, db: AsyncSession) -> DomainConfig:
        cached = self._cache.get(domain_id)
        if cached is not None:
            return cached

        config = await self._load_domain(domain_id, db)
        if config is not None:
            self._cache[domain_id] = config
            return config

        if domain_id != "default":
            fallback = await self._load_domain("default", db)
            if fallback is not None:
                self._cache["default"] = fallback
                return fallback

        raise ValueError(f"Domain not found: {domain_id}")

    async def list_enabled(self, db: AsyncSession) -> list[DomainConfig]:
        result = await db.execute(
            select(Domain)
            .where(Domain.enabled == True, Domain.domain_id != "default")
            .options(selectinload(Domain.prompts), selectinload(Domain.clarification_fields))
            .order_by(Domain.display_name)
        )
        return [self._to_config(domain) for domain in result.scalars().all()]

    def invalidate(self, domain_id: str) -> None:
        self._cache.pop(domain_id, None)

    async def get_prompt(self, domain_id: str, prompt_type: str, db: AsyncSession) -> str:
        config = await self.get_domain(domain_id, db)
        return config.prompts.get(prompt_type, "")

    async def get_clarification_fields(self, domain_id: str, db: AsyncSession) -> list[dict[str, Any]]:
        """Возвращает только поля с required=True.
        Если таких нет — Planner пропускает LLM-вызов кларификации.
        """
        config = await self.get_domain(domain_id, db)
        return [f for f in config.clarification_fields if f.get("required", True)]

    async def list_domains(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(select(Domain).order_by(Domain.domain_id))
        return [self._domain_dict(domain) for domain in result.scalars().all()]

    async def create_domain(self, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        domain_id = str(data["domain_id"])
        if await db.get(Domain, domain_id) is not None:
            raise ValueError("Domain already exists")
        domain = Domain(
            domain_id=domain_id,
            display_name=data["display_name"],
            description=data.get("description"),
            enabled=bool(data.get("enabled", True)),
            is_system=False,
        )
        async with transactional(db):
            db.add(domain)
            for prompt_type in ("system", "clarification", "planner", "pipeline_router"):
                db.add(DomainPrompt(domain_id=domain_id, prompt_type=prompt_type, content=""))
        await db.refresh(domain)
        self.invalidate(domain_id)
        return self._domain_dict(domain)

    async def update_domain(self, domain_id: str, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        domain = await db.get(Domain, domain_id)
        if domain is None:
            raise KeyError(domain_id)
        async with transactional(db):
            for field in ("display_name", "description", "enabled"):
                if field in data:
                    setattr(domain, field, data[field])
        await db.refresh(domain)
        self.invalidate(domain_id)
        return self._domain_dict(domain)

    async def delete_domain(self, domain_id: str, db: AsyncSession) -> None:
        domain = await db.get(Domain, domain_id)
        if domain is None:
            raise KeyError(domain_id)
        if domain.is_system:
            raise ValueError("Cannot delete system domain")
        result = await db.execute(select(func.count()).select_from(Vault).where(Vault.domain_id == domain_id))
        if result.scalar_one() > 0:
            raise ValueError("Cannot delete domain: vaults still exist")
        async with transactional(db):
            await db.delete(domain)
        self.invalidate(domain_id)

    async def update_prompts(self, domain_id: str, prompts: dict[str, str], db: AsyncSession) -> None:
        if await db.get(Domain, domain_id) is None:
            raise KeyError(domain_id)
        async with transactional(db):
            for prompt_type, content in prompts.items():
                result = await db.execute(
                    select(DomainPrompt).where(DomainPrompt.domain_id == domain_id, DomainPrompt.prompt_type == prompt_type)
                )
                prompt = result.scalar_one_or_none()
                if prompt is None:
                    db.add(DomainPrompt(domain_id=domain_id, prompt_type=prompt_type, content=content))
                else:
                    prompt.content = content
        self.invalidate(domain_id)

    async def update_clarification_fields(self, domain_id: str, fields: list[dict[str, Any]], db: AsyncSession) -> None:
        if await db.get(Domain, domain_id) is None:
            raise KeyError(domain_id)

        existing_result = await db.execute(select(DomainClarificationField).where(DomainClarificationField.domain_id == domain_id))
        existing_names = {field.field_name for field in existing_result.scalars().all()}
        new_names = {str(field["field_name"]) for field in fields}
        removed = existing_names - new_names
        if removed and not await self.can_delete_fields(domain_id, sorted(removed), db):
            raise ValueError("Cannot delete clarification fields used by active states")

        async with transactional(db):
            await db.execute(delete(DomainClarificationField).where(DomainClarificationField.domain_id == domain_id))
            for index, field in enumerate(fields):
                db.add(
                    DomainClarificationField(
                        domain_id=domain_id,
                        field_name=str(field["field_name"]),
                        label=str(field["label"]),
                        hint=field.get("hint"),
                        required=bool(field.get("required", True)),
                        display_order=int(field.get("display_order", index)),
                    )
                )
        self.invalidate(domain_id)

    async def can_delete_fields(self, domain_id: str, field_names: list[str], db: AsyncSession) -> bool:
        if not field_names:
            return True
        result = await db.execute(select(ClarificationState).where(ClarificationState.stage == "collecting"))
        blocked = set(field_names)
        for state in result.scalars().all():
            missing_fields = state.missing_fields or []
            if any(field in blocked for field in missing_fields):
                return False
        return True

    async def _load_domain(self, domain_id: str, db: AsyncSession) -> DomainConfig | None:
        result = await db.execute(
            select(Domain)
            .where(Domain.domain_id == domain_id)
            .options(selectinload(Domain.prompts), selectinload(Domain.clarification_fields))
        )
        domain = result.scalar_one_or_none()
        return self._to_config(domain) if domain is not None else None

    def _to_config(self, domain: Domain) -> DomainConfig:
        return DomainConfig(
            domain_id=domain.domain_id,
            display_name=domain.display_name,
            enabled=domain.enabled,
            prompts={prompt.prompt_type: prompt.content for prompt in domain.prompts},
            clarification_fields=[
                {
                    "field_name": field.field_name,
                    "label": field.label,
                    "hint": field.hint,
                    "required": field.required,
                    "display_order": field.display_order,
                }
                for field in sorted(domain.clarification_fields, key=lambda item: item.display_order)
            ],
        )

    def _domain_dict(self, domain: Domain) -> dict[str, Any]:
        return {
            "domain_id": domain.domain_id,
            "display_name": domain.display_name,
            "description": domain.description,
            "is_system": domain.is_system,
            "enabled": domain.enabled,
            "created_at": domain.created_at,
            "updated_at": domain.updated_at,
        }


domain_service = DomainService()
