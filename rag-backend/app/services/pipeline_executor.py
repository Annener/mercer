from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat
from app.services.pipeline_dag import get_execution_levels
from app.services.retrieval import (
    format_context_with_role,
    get_document_ids_by_tags,
    retrieve,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from shared_contracts.models import (
    PipelineExecutionContext,
    PipelineStep,
    SearchHit,
)

logger = logging.getLogger(__name__)

# Validation token живёт 1 час (по концепту)
_VALIDATION_TTL = timedelta(hours=1)


# =============================================================================
# Module-level shim — для обратной совместимости тестов
# тесты импортируют: from app.services.pipeline_executor import _build_levels
# =============================================================================

def _build_levels(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Shim: перенаправляет вызов в get_execution_levels() из pipeline_dag.

    Оставлен для обратной совместимости импорта в тестах.
    Используйте get_execution_levels() напрямую в новом коде.
    """
    return get_execution_levels(steps)


def _resolve_prompt(template: str, ctx: PipelineExecutionContext) -> str:
    """Подставить {query}, {STEP_ID.result}, {STEP_ID.key} в шаблон промта."""
    result = template.replace("{query}", ctx.query)
    for step_id, value in ctx.step_results.items():
        if step_id.startswith("_"):
            continue
        result = result.replace(f"{{{step_id}.result}}", str(value))
        if isinstance(value, dict):
            for k, v in value.items():
                result = result.replace(f"{{{step_id}.{k}}}", str(v))
    return result


# =============================================================================
# PipelineExecutor
# =============================================================================

class PipelineExecutor:
    """Выполняет пайплайн базируясь на DAG с поддержкой validation-пауз.

    Public API:
        run_stream(ctx)                  -> AsyncIterator[dict]
        resume_from_validation(ctx, sid) -> AsyncIterator[dict]
    """

    def __init__(
        self,
        db: AsyncSession,
        session_factory=None,
    ) -> None:
        self.db = db
        self._session_factory = session_factory

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def run_stream(
        self,
        ctx: PipelineExecutionContext,
    ) -> AsyncIterator[dict[str, Any]]:
        """Запустить пайплайн с 0-го уровня DAG."""
        async for chunk in self._dag_execute(ctx, start_after_step=None):
            yield chunk

    async def resume_from_validation(
        self,
        ctx: PipelineExecutionContext,
        validated_step_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Продолжить пайплайн после пользовательского ответа на validation-шаг."""
        async for chunk in self._dag_execute(ctx, start_after_step=validated_step_id):
            yield chunk

    # -------------------------------------------------------------------------
    # Core DAG async generator
    # -------------------------------------------------------------------------

    async def _dag_execute(
        self,
        ctx: PipelineExecutionContext,
        start_after_step: str | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        provider = settings_service.get_active_provider()
        if provider is None:
            yield {"type": "error", "message": "No active model configured"}
            return

        yield {"type": "pipeline_selected", "pipeline_id": ctx.pipeline_id}

        levels = get_execution_levels(ctx.steps)

        start_level = 0
        if start_after_step is not None:
            for lvl_idx, level in enumerate(levels):
                for step in level:
                    if step.step_id == start_after_step:
                        start_level = lvl_idx + 1
                        break

        for level in levels[start_level:]:
            if len(level) == 1:
                stop = False
                async for chunk in self._run_dag_step(level[0], ctx, provider):
                    if chunk.get("__stop__"):
                        yield chunk["__payload__"]
                        stop = True
                        break
                    yield chunk
                if stop:
                    return
            else:
                stop = False
                async for chunk in self._run_parallel_level(level, ctx, provider):
                    if chunk.get("__stop__"):
                        yield chunk["__payload__"]
                        stop = True
                        break
                    yield chunk
                if stop:
                    return

        async for chunk in self._run_final_composition(ctx, provider):
            yield chunk

    async def _run_dag_step(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if step.type == "validation":
            async for chunk in self._run_validation_step(step, ctx):
                yield chunk
            return

        hits = await self._retrieve_for_step_dag(step, ctx)
        if not hits:
            # Не перезаписываем результат, если он уже установлен
            # (например, передан через context_snapshot при resume или в тесте).
            if step.step_id not in ctx.step_results:
                ctx.step_results[step.step_id] = ""
            yield {"type": "step_skipped_no_docs", "step_id": step.step_id, "step_name": step.name}
            return

        formatted = format_context_with_role(hits, getattr(step, "role", None))
        ctx.step_results[step.step_id] = formatted
        yield {"type": "step_complete", "step_id": step.step_id, "step_name": step.name}

    async def _run_validation_step(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
    ) -> AsyncGenerator[dict[str, Any], None]:
        resume_token = secrets.token_urlsafe(32)
        await self._save_pause_state(ctx, step.step_id, step.name, resume_token)
        content = _resolve_prompt(
            step.validation_prompt or step.system_prompt or "",
            ctx,
        )
        yield {
            "__stop__": True,
            "__payload__": {
                "type": "validation_required",
                "step_id": step.step_id,
                "step_name": step.name,
                "content": content,
                "options": step.options or [],
                "resume_token": resume_token,
            },
        }

    async def _run_parallel_level(
        self,
        steps: list[PipelineStep],
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """asyncio.gather() для шагов одного уровня с независимыми DB-сессиями."""
        if not self._session_factory:
            logger.warning(
                "PipelineExecutor: no session_factory — parallel steps run sequentially. "
                "Pass session_factory=async_sessionmaker to enable true parallelism."
            )
            for step in steps:
                async for chunk in self._run_dag_step(step, ctx, provider):
                    yield chunk
            return

        async def _step_with_session(step: PipelineStep) -> list[dict]:
            chunks: list[dict] = []
            async with self._session_factory() as session:
                orig_db = self.db
                self.db = session
                try:
                    async for chunk in self._run_dag_step(step, ctx, provider):
                        chunks.append(chunk)
                finally:
                    self.db = orig_db
            return chunks

        results = await asyncio.gather(
            *[_step_with_session(step) for step in steps],
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.error("Parallel step error: %s", result, exc_info=True)
                yield {"type": "error", "message": str(result)}
                continue
            for chunk in result:
                yield chunk

    async def _run_final_composition(
        self,
        ctx: PipelineExecutionContext,
        provider: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        prompt = _resolve_prompt(ctx.final_composition.system_prompt, ctx)
        try:
            async for token in provider.generate_stream([
                {"role": "system", "content": prompt},
                {"role": "user", "content": ctx.query},
            ]):
                yield {"type": "token", "content": token}
        except Exception as exc:
            logger.error("FinalComposition stream error: %s", exc, exc_info=True)
            yield {"type": "error", "message": f"LLM stream error: {exc}"}
            return
        yield {"type": "pipeline_complete"}

    async def _retrieve_for_step_dag(
        self,
        step: PipelineStep,
        ctx: PipelineExecutionContext,
    ) -> list[SearchHit]:
        """Retrieval для DAG-шага через ctx.vault_ids + step.tag_ids."""
        top_k = step.top_k or int(await settings_service.get("retrieval.top_k"))
        vault_ids: list[str] = ctx.vault_ids or []

        if not vault_ids:
            logger.warning("Step skipped: no vault_ids in context. step=%s", step.step_id)
            return []

        document_ids: list[str] | None = None
        if step.tag_ids:
            domain_id = ctx.domain_id
            if not domain_id:
                logger.warning("Step skipped: tag_ids set but no domain_id. step=%s", step.step_id)
                return []
            document_ids = await get_document_ids_by_tags(step.tag_ids, domain_id, self.db)
            if document_ids == []:
                logger.info("Step skipped: no indexed docs for tag_ids. step=%s", step.step_id)
                return []

        if len(vault_ids) == 1:
            return await retrieve(ctx.query, vault_ids[0], document_ids=document_ids, top_k=top_k, db=self.db)
        return await retrieve_multi_vault(ctx.query, vault_ids, document_ids=document_ids, top_k=top_k, db=self.db)

    async def _save_pause_state(
        self,
        ctx: PipelineExecutionContext,
        step_id: str,
        step_name: str,
        resume_token: str,
    ) -> None:
        """Сохранить pipeline_pause_state в Chat.

        context_snapshot — полный дамп контекста через model_dump(),
        чтобы _restore_context() в pipeline_resume.py мог полностью восстановить
        PipelineExecutionContext включая steps, final_composition, pipeline_id и все vault_ids.
        """
        try:
            chat = await self.db.get(Chat, uuid.UUID(ctx.chat_id))
            if chat is None:
                logger.warning("_save_pause_state: chat %s not found", ctx.chat_id)
                return
            chat.pipeline_pause_state = {
                "pipeline_id": ctx.pipeline_id,
                "step_id": step_id,
                "step_name": step_name,
                "resume_token": resume_token,
                "query": ctx.query,
                "context_snapshot": ctx.model_dump(mode="json"),
                "expires_at": (datetime.now(UTC) + _VALIDATION_TTL).isoformat(),
            }
            await self.db.commit()
        except Exception as exc:
            logger.warning("_save_pause_state failed: %s", exc)
