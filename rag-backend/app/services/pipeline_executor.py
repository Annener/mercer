from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat
from app.services.pipeline_dag import get_execution_levels
from app.services.query_rewriter import query_rewriter
from app.services.retrieval import (
    format_context_with_role,
    get_document_ids_by_tags,
    rerank_hits,
    retrieve,
    retrieve_multi_vault,
)
from app.services.settings_service import settings_service
from shared_contracts.models import (
    DocumentCandidate,
    PipelineExecutionContext,
    PipelineStep,
    SearchHit,
)

logger = logging.getLogger(__name__)

# URL сервиса хранилища чанков (db-api-server).
STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")


def _status(text: str) -> dict:
    """Emits a step_status chunk for displaying progress in the frontend."""
    return {"type": "step_status", "text": text}


# Validation token lives 1 hour.
_VALIDATION_TTL = timedelta(hours=1)

# Ключ в ctx.step_results для накопления сырых SearchHit по шагам.
# Начинается с "_" — _resolve_prompt игнорирует такие ключи.
_HITS_KEY_PREFIX = "_hits_"


# =============================================================================
# Module-level shim
# =============================================================================

def _build_levels(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Shim: redirects to get_execution_levels() from pipeline_dag.

    Kept for backward compatibility with tests.
    """
    return get_execution_levels(steps)


def _resolve_prompt(template: str, ctx: PipelineExecutionContext) -> str:
    """Substitute {query}, {STEP_ID.result}, {STEP_ID.key} in prompt template.

    {query} resolves to ctx.original_query if set (the full user message before
    QueryRewriter rewrites it for vector search), otherwise falls back to ctx.query.
    This ensures the final composition prompt receives the complete user intent,
    not a truncated retrieval-optimised phrase.
    """
    user_query = ctx.original_query if ctx.original_query else ctx.query
    result = template.replace("{query}", user_query)
    for step_id, value in ctx.step_results.items():
        if step_id.startswith("_"):
            continue
        result = result.replace(f"{{{step_id}.result}}", str(value))
        if isinstance(value, dict):
            for k, v in value.items():
                result = result.replace(f"{{{step_id}.{k}}}", str(v))
    return result


def _collect_all_hits(ctx: PipelineExecutionContext) -> list[SearchHit]:
    """Собирает все накопленные SearchHit из ctx.step_results (_hits_* ключи)."""
    all_hits: list[SearchHit] = []
    seen_chunk_ids: set[str] = set()
    for key, value in ctx.step_results.items():
        if not key.startswith(_HITS_KEY_PREFIX):
            continue
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, SearchHit):
                hit = item
            elif isinstance(item, dict):
                try:
                    hit = SearchHit.model_validate(item)
                except Exception:
                    continue
            else:
                continue
            if hit.chunk_id not in seen_chunk_ids:
                seen_chunk_ids.add(hit.chunk_id)
                all_hits.append(hit)
    return all_hits


# =============================================================================
# PipelineExecutor
# =============================================================================

class PipelineExecutor:
    """Executes pipeline DAG with validation-pause and full_document_selection support.

    Public API:
        run_stream(ctx)                              -> AsyncIterator[dict]
        resume_from_validation(ctx, sid)             -> AsyncIterator[dict]
        resume_from_full_doc_selection(chat_id, ...) -> AsyncIterator[dict]
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
        """Start pipeline from DAG level 0."""
        async for chunk in self._dag_execute(ctx, start_after_step=None):
            yield chunk

    async def resume_from_validation(
        self,
        ctx: PipelineExecutionContext,
        validated_step_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Continue pipeline after user response to a validation step."""
        async for chunk in self._dag_execute(ctx, start_after_step=validated_step_id):
            yield chunk

    async def resume_from_full_doc_selection(
        self,
        chat_id: str,
        selected_document_ids: list[str],
        db: AsyncSession,
    ) -> AsyncIterator[dict[str, Any]]:
        """Возобновить пайплайн после выбора полных документов пользователем.

        Алгоритм:
        1. Читаем pipeline_pause_state из Chat — там saved_hits, candidates, context_snapshot.
        2. Проверяем pipeline_id в context_snapshot:
           - Если None → plain-fallback ветка (без DAG): _resolve_system_prompt +
             assemble_hybrid_context + provider.generate_stream напрямую.
           - Если задан → полный пайплайн (оригинальная логика с final_composition).
        3. Загружаем full texts для selected_document_ids (параллельно).
        4. Собираем hybrid context через assemble_hybrid_context.
        5. Обновляем chat.sent_full_document_ids.
        6. Очищаем pipeline_pause_state.
        7a. (plain-fallback) Вызываем LLM напрямую, сохраняем Message.
        7b. (pipeline) Записываем hybrid context в ctx.step_results, запускаем
            _run_final_composition.
        """
        from app.services.full_document_service import (
            assemble_hybrid_context,
            reconstruct_full_text,
        )

        provider = settings_service.get_active_provider()
        if provider is None:
            yield {"type": "error", "message": "No active model configured"}
            return

        # 1. Загружаем pause state
        try:
            chat_uuid = uuid.UUID(chat_id)
        except ValueError:
            yield {"type": "error", "message": f"Invalid chat_id: {chat_id}"}
            return

        chat = await db.get(Chat, chat_uuid)
        if chat is None:
            yield {"type": "error", "message": f"Chat {chat_id} not found"}
            return

        pause_state = chat.pipeline_pause_state
        if not pause_state or pause_state.get("step") != "full_document_selection":
            yield {"type": "error", "message": "No active full_document_selection pause"}
            return

        # Восстанавливаем данные из pause_state
        saved_hits_raw: list[dict] = pause_state.get("saved_hits", [])
        candidates_raw: list[dict] = pause_state.get("candidates", [])
        context_snapshot: dict[str, Any] = pause_state.get("context_snapshot", {})

        saved_hits: list[SearchHit] = []
        for h in saved_hits_raw:
            try:
                saved_hits.append(SearchHit.model_validate(h))
            except Exception:
                pass

        candidates: list[DocumentCandidate] = []
        for c in candidates_raw:
            try:
                candidates.append(DocumentCandidate.model_validate(c))
            except Exception:
                pass

        # 2. Загружаем full texts параллельно
        full_texts: dict[str, str] = {}
        if selected_document_ids:
            yield _status("Загружаю полные тексты документов...")

            # Для каждого selected_doc_id нужен vault_id.
            # Ищем vault_id в saved_hits: hit.metadata может содержать vault_id,
            # либо берём из vault_ids контекста (первый vault если один).
            vault_ids_from_ctx: list[str] = context_snapshot.get("vault_ids", [])

            doc_vault_map: dict[str, str] = {}
            for hit in saved_hits:
                if hit.document_id in selected_document_ids:
                    vault_id = hit.metadata.get("vault_id") or (
                        vault_ids_from_ctx[0] if len(vault_ids_from_ctx) == 1 else None
                    )
                    if vault_id and hit.document_id not in doc_vault_map:
                        doc_vault_map[hit.document_id] = vault_id

            # Для документов без vault_id из hits — пробуем fallback через БД
            missing = [did for did in selected_document_ids if did not in doc_vault_map]
            if missing and vault_ids_from_ctx:
                for did in missing:
                    # Используем первый vault как fallback (типичный кейс: один vault)
                    doc_vault_map[did] = vault_ids_from_ctx[0]
                    logger.info(
                        "resume_from_full_doc_selection: vault_id fallback for doc=%s → %s",
                        did, vault_ids_from_ctx[0],
                    )

            async def _fetch_text(doc_id: str) -> tuple[str, str | None]:
                vault_id = doc_vault_map.get(doc_id)
                if not vault_id:
                    logger.warning(
                        "resume_from_full_doc_selection: no vault_id for doc=%s — skipping",
                        doc_id,
                    )
                    return doc_id, None
                text = await reconstruct_full_text(doc_id, vault_id, STORAGE_API_URL)
                return doc_id, text

            results = await asyncio.gather(
                *[_fetch_text(did) for did in selected_document_ids],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("resume_from_full_doc_selection: fetch error: %s", result)
                    continue
                doc_id, text = result
                if text:
                    full_texts[doc_id] = text

        # 3. Собираем hybrid context
        context_str = assemble_hybrid_context(
            selected_doc_ids=selected_document_ids,
            full_texts=full_texts,
            hits=saved_hits,
            candidates=candidates,
        )

        # 4 + 5. Обновляем sent_full_document_ids и очищаем pause_state
        try:
            existing_sent: list[str] = list(chat.sent_full_document_ids or [])
            for did in selected_document_ids:
                if did not in existing_sent:
                    existing_sent.append(did)
            chat.sent_full_document_ids = existing_sent
            chat.pipeline_pause_state = None
            await db.commit()
        except Exception as exc:
            logger.warning("resume_from_full_doc_selection: failed to update chat: %s", exc)

        # ── Проверяем: это plain-fallback пауза или пауза из полноценного пайплайна?
        pipeline_id = context_snapshot.get("pipeline_id")

        if not pipeline_id:
            # ── 7a. Plain-fallback ветка ──────────────────────────────────────
            # pipeline_id отсутствует → пауза пришла из plain_stream в chat.py.
            # Запускаем LLM напрямую, без DAG и final_composition.
            logger.info(
                "resume_from_full_doc_selection: plain-fallback branch (no pipeline_id). "
                "chat_id=%s", chat_id,
            )
            from app.api.chat import _resolve_system_prompt

            campaign_id: str | None = context_snapshot.get("campaign_id")
            domain_id: str | None = context_snapshot.get("domain_id")
            original_query: str = context_snapshot.get("original_query") or context_snapshot.get("query", "")

            system_prompt = await _resolve_system_prompt(campaign_id, domain_id, db)
            full_system = f"{system_prompt}\n\n{context_str}" if system_prompt else context_str

            messages: list[dict[str, str]] = []
            if full_system:
                messages.append({"role": "system", "content": full_system})
            messages.append({"role": "user", "content": original_query})

            yield _status("Генерирую ответ...")
            full_answer = ""
            try:
                async for token in provider.generate_stream(messages):
                    full_answer += token
                    yield {"type": "token", "content": token}
            except Exception as exc:
                logger.error(
                    "resume_from_full_doc_selection plain-fallback stream error: %s",
                    exc, exc_info=True,
                )
                yield {"type": "error", "message": f"LLM stream error: {exc}"}
                return

            # Сохраняем ответ в Message
            try:
                from app.db.models import Message
                assistant_msg = Message(
                    chat_id=chat_uuid,
                    role="assistant",
                    content=full_answer,
                )
                db.add(assistant_msg)
                await db.commit()
            except Exception as exc:
                logger.warning(
                    "resume_from_full_doc_selection: failed to save assistant message: %s", exc,
                )

            yield {"type": "pipeline_complete"}
            return

        # ── 7b. Полный пайплайн: восстанавливаем контекст и запускаем final_composition
        from shared_contracts.models import PipelineExecutionContext as PEC
        ctx_data = {
            "query": "",
            "message_id": str(uuid.uuid4()),
            **context_snapshot,
            "chat_id": chat_id,
        }
        ctx = PEC.model_validate(ctx_data)

        if ctx.final_composition is None:
            logger.error(
                "resume_from_full_doc_selection: final_composition is None in context_snapshot. "
                "chat_id=%s", chat_id,
            )
            yield {"type": "error", "message": "Pipeline misconfiguration: final_composition missing in context snapshot"}
            return

        # Записываем hybrid context под специальный ключ — он будет доступен
        # через {_fulldoc_context.result} если нужен в промпте,
        # но главное — перезаписываем все retrieval step_results hybrid-контекстом.
        # Стратегия: находим retrieval-шаги и заменяем их результат hybrid-строкой.
        # Это гарантирует что _resolve_prompt в _run_final_composition использует
        # hybrid context вместо старых отформатированных чанков.
        if ctx.steps and context_str:
            retrieval_step_ids = [
                s.step_id for s in ctx.steps if s.type == "retrieval"
            ]
            if retrieval_step_ids:
                # Помещаем весь hybrid context в первый retrieval шаг,
                # остальные обнуляем (уже вошли в hybrid)
                first_id = retrieval_step_ids[0]
                ctx.step_results[first_id] = context_str
                for sid in retrieval_step_ids[1:]:
                    ctx.step_results[sid] = ""
            else:
                # Нет явных retrieval шагов — используем служебный ключ
                ctx.step_results["_fulldoc_context"] = context_str

        # Запускаем финальную композицию
        async for chunk in self._run_final_composition(ctx, provider):
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

        # --- Full Document Mode: пауза перед финальной композицией ---
        async for chunk in self._maybe_pause_for_full_doc(ctx):
            if chunk.get("__stop__"):
                yield chunk["__payload__"]
                return
            yield chunk

        logger.info(
            "All DAG levels complete, starting final_composition. step_results keys=%s",
            list(ctx.step_results.keys()),
        )
        async for chunk in self._run_final_composition(ctx, provider):
            yield chunk

    async def _maybe_pause_for_full_doc(
        self,
        ctx: PipelineExecutionContext,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Проверяет нужна ли пауза full_document_selection.

        Если full_document_mode_enabled=True и есть кандидаты → сохраняет
        pause_state и эмитирует __stop__ с full_document_selection_required.
        Иначе — ничего не эмитирует (пайплайн продолжается).
        """
        from app.services.full_document_service import collect_document_candidates

        # Загружаем Chat для проверки флага
        try:
            chat_uuid = uuid.UUID(ctx.chat_id)
        except ValueError:
            return  # невалидный chat_id — не прерываем пайплайн
        chat = await self.db.get(Chat, chat_uuid)
        if chat is None or not chat.full_document_mode_enabled:
            return  # режим выключен → продолжаем обычно

        # Собираем все хиты из всех шагов
        all_hits = _collect_all_hits(ctx)
        if not all_hits:
            logger.info(
                "_maybe_pause_for_full_doc: no hits accumulated, skipping full_doc pause. "
                "chat=%s", ctx.chat_id,
            )
            return

        sent_ids: list[str] = list(chat.sent_full_document_ids or [])
        candidates = await collect_document_candidates(all_hits, sent_ids, self.db)

        if not candidates:
            logger.info(
                "_maybe_pause_for_full_doc: no candidates after filtering. chat=%s",
                ctx.chat_id,
            )
            return

        # Сохраняем pause_state
        pause_state = {
            "step": "full_document_selection",
            "candidates": [c.model_dump() for c in candidates],
            "saved_hits": [h.model_dump() for h in all_hits],
            "context_snapshot": ctx.model_dump(mode="json"),
            "expires_at": (datetime.now(UTC) + _VALIDATION_TTL).isoformat(),
        }
        try:
            chat.pipeline_pause_state = pause_state
            await self.db.commit()
        except Exception as exc:
            logger.warning("_maybe_pause_for_full_doc: failed to save pause_state: %s", exc)
            return  # не прерываем пайплайн если сохранение упало

        logger.info(
            "_maybe_pause_for_full_doc: pausing for full_document_selection. "
            "chat=%s candidates=%d", ctx.chat_id, len(candidates),
        )

        yield {
            "__stop__": True,
            "__payload__": {
                "type": "full_document_selection_required",
                "candidates": [c.model_dump() for c in candidates],
            },
        }

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

        # --- Retrieval --------------------------------------------------
        yield _status(f"Searching knowledge base: {step.name}...")
        try:
            hits = await self._retrieve_for_step_dag(step, ctx, provider)
        except Exception as exc:
            logger.error(
                "Step retrieval error: step=%s err=%s", step.step_id, exc, exc_info=True
            )
            ctx.step_results[step.step_id] = ""
            yield {"type": "step_error", "step_id": step.step_id, "message": str(exc)}
            return

        if not hits:
            if step.step_id not in ctx.step_results:
                ctx.step_results[step.step_id] = ""
            yield {"type": "step_skipped_no_docs", "step_id": step.step_id, "step_name": step.name}
            return

        # --- Rerank (explicit, so we can emit a status before it) -------
        if len(hits) > 1:
            yield _status(f"Reranking results: {step.name}...")
            try:
                hits = await rerank_hits(ctx.query, hits, self.db)
            except Exception as exc:
                logger.warning(
                    "Rerank failed for step=%s, using original order: %s",
                    step.step_id, exc,
                )

        # Накапливаем сырые хиты для возможной full_document_selection паузы.
        # Ключ начинается с "_" — _resolve_prompt его игнорирует.
        ctx.step_results[f"{_HITS_KEY_PREFIX}{step.step_id}"] = [
            h.model_dump() for h in hits
        ]

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
        """asyncio.gather() for steps in same level with independent DB sessions."""
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
        # Use the original unmodified user query as the user-role message so the
        # LLM receives the full intent, not the retrieval-optimised short phrase.
        user_content = ctx.original_query if ctx.original_query else ctx.query
        yield _status("Генерирую ответ...")
        try:
            async for token in provider.generate_stream([
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
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
        provider: Any,
    ) -> list[SearchHit]:
        """Retrieval for a DAG step (without rerank — caller handles it explicitly).

        Search query is built from step.system_prompt only:
        - _resolve_prompt substitutes {query} with original_query if present in template
        - rewrite_for_retrieval compresses the resolved prompt into a short search phrase

        ctx.query is intentionally NOT passed to rewrite_for_retrieval — mixing it
        with step_prompt was causing incorrect search queries (step intent lost).
        """
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

        # _resolve_prompt подставляет {query} → original_query если она есть в шаблоне.
        # Если {query} нет — step_prompt остаётся как есть (детерминированный запрос).
        step_prompt = _resolve_prompt(step.system_prompt or "", ctx)

        # rewrite_for_retrieval получает только step_prompt — единственный источник.
        # ctx.query намеренно не передаётся: его подмешивание ломало intent шага.
        search_query = await query_rewriter.rewrite_for_retrieval(
            step_prompt,
            provider,
        )
        logger.info(
            "RETRIEVE step=%s step_prompt='%s' search_query='%s'",
            step.step_id,
            step_prompt[:80],
            search_query[:80],
        )

        if len(vault_ids) == 1:
            return await retrieve(
                search_query, vault_ids[0],
                document_ids=document_ids, top_k=top_k, db=self.db,
            )
        # skip_rerank=True: rerank happens explicitly in _run_dag_step after status emit
        return await retrieve_multi_vault(
            search_query, vault_ids,
            document_ids=document_ids, top_k=top_k, db=self.db,
            skip_rerank=True,
        )

    async def _save_pause_state(
        self,
        ctx: PipelineExecutionContext,
        step_id: str,
        step_name: str,
        resume_token: str,
    ) -> None:
        """Save pipeline_pause_state in Chat.

        context_snapshot is a full context dump via model_dump(),
        so _restore_context() in pipeline_resume.py can fully restore
        PipelineExecutionContext including steps, final_composition, pipeline_id and vault_ids.
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
