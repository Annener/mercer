"""context_engine.loop — DriftLoop с cooldown + idle scan + status bus.

Запускается в FastAPI lifespan. На каждый chat turn (через
``trigger_for_chat``) проверяет Redis SETNX cooldown-ключ; если не
выставлен — ставит на 30 сек и запускает ``DriftDetector.detect`` в
fire-and-forget asyncio task.

Параллельно крутится ``run_idle_scan`` (каждые 60 сек) — fallback для
чатов, помеченных в Redis set ``drift:dirty``, у которых direct trigger
провалился (Redis SETNX упал с ошибкой).

Все ошибки (Redis, detector, провайдер) логируются и тихо глотаются —
фазовый сбой drift не должен влиять на основной chat-loop.

Master switch: ``drift.enabled`` (PlatformSetting). Если флаг выключен
— ни trigger, ни idle scan не запускают detector. Также читаются
``drift.detect_enabled`` и ``drift.draft_enabled`` для раздельного
управления стадиями.

Status bus: ``status_bus`` публикует ``DriftStatus`` (фазы detecting /
drafting / draft_ready / idle / error) для подписчиков SSE/poll.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from shared_contracts.models import DriftPhase, DriftStatus

from .drift import DriftDetector

if TYPE_CHECKING:
    from .draft import CampaignStateDrafter
    from .status_bus import DriftStatusBus


logger = logging.getLogger(__name__)


# Cooldown per-chat — не чаще 1 раза в N секунд.
_COOLDOWN_SECONDS = 30
_COOLDOWN_KEY = "drift:cooldown:{chat_id}"

# Dirty set — для idle scan fallback.
_DIRTY_SET_KEY = "drift:dirty"

# Idle scan период.
_IDLE_SCAN_PERIOD_SECONDS = 60

# Кеш PlatformSetting-флагов (drift.enabled и дочерние).
_FLAG_CACHE_TTL_SECONDS = 5.0

# Сообщения для UI — короткие и человеко-читаемые.
_DETECTING_MESSAGE = "Анализирую последние сообщения на расхождения с контекстом…"
_DRAFTING_MESSAGE = "Готовлю предложения по обновлению контекста…"


def _now() -> "Any":
    """Timezone-aware UTC now (нужно для DriftStatus)."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _build_draft_preview(state_patch: list[dict[str, Any]], summary: str) -> str:
    """Сформировать короткий превью draft для UI.

    Возвращает ``summary`` если не пустой, иначе — перечисление первых
    одной-двух операций с типом и field_key.
    """
    if summary:
        text = summary.strip()
        if text:
            return text if len(text) <= 200 else text[:197] + "…"

    if not state_patch:
        return ""
    parts: list[str] = []
    for op in state_patch[:2]:
        if not isinstance(op, dict):
            continue
        op_type = str(op.get("type", ""))
        field = str(op.get("field_key", ""))
        item = op.get("item_key")
        target = f"{field}.{item}" if item else field
        parts.append(f"{op_type}:{target}" if op_type else target)
    suffix = "" if len(state_patch) <= 2 else f" (+{len(state_patch) - 2})"
    return ", ".join(parts) + suffix


class DriftLoop:
    """Background loop с cooldown для drift-detection."""

    def __init__(
        self,
        *,
        detector: DriftDetector,
        redis: aioredis.Redis,
        cooldown_seconds: int = _COOLDOWN_SECONDS,
        idle_scan_period_seconds: int = _IDLE_SCAN_PERIOD_SECONDS,
        status_bus: "DriftStatusBus | None" = None,
    ) -> None:
        self.detector = detector
        self.redis = redis
        self.cooldown_seconds = cooldown_seconds
        self.idle_scan_period_seconds = idle_scan_period_seconds
        self.status_bus = status_bus
        # Phase 3: drafter планирует draft на основе drift hints.
        # Устанавливается через ``drift_loop.drafter = ...`` в lifespan
        # (или напрямую в тестах). Если None — detect работает, но draft
        # не создаётся (логируется INFO).
        self.drafter: "CampaignStateDrafter | None" = None
        self._idle_task: asyncio.Task | None = None
        self._shutdown = asyncio.Event()
        # Platform flag cache: пары (enabled, detect_enabled, draft_enabled) + ts.
        self._flags_cache: tuple[bool, bool, bool, float] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trigger_for_chat(self, chat_id: str) -> None:
        """Fire-and-forget запуск drift для одного чата. Cooldown через Redis SETNX.

        Перед cooldown-проверкой читает флаги:
        - ``drift.enabled`` — мастер. False → сразу return;
        - ``drift.detect_enabled`` — отдельный стоп-кран для детектора.

        Idle scan использует тот же путь и, если флаги выключены,
        тихо пропускает все dirty-чаты.
        """
        if not chat_id:
            return

        flags = await self._get_flags()
        if not flags.enabled or not flags.detect_enabled:
            logger.debug(
                "drift_loop.trigger_for_chat: disabled by flags chat_id=%s flags=%s",
                chat_id,
                flags,
            )
            return

        cooldown_key = _COOLDOWN_KEY.format(chat_id=chat_id)
        try:
            acquired = await self.redis.set(
                cooldown_key,
                "1",
                ex=self.cooldown_seconds,
                nx=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Redis упал — не блокируем drift-detection, но помечаем чат
            # в dirty set, чтобы idle scan попробовал позже.
            logger.warning(
                "drift_loop.trigger_for_chat: redis SETNX failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            acquired = True

        if not acquired:
            logger.debug(
                "drift_loop.trigger_for_chat: cooldown active chat_id=%s, skip",
                chat_id,
            )
            return

        # Mark dirty для fallback.
        try:
            await self.redis.sadd(_DIRTY_SET_KEY, chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift_loop.trigger_for_chat: redis SADD failed chat_id=%s: %s",
                chat_id,
                exc,
            )

        # Fire-and-forget task — exceptions логируются внутри _run_detect.
        try:
            asyncio.create_task(self._run_detect(chat_id))
        except RuntimeError:
            # event loop закрыт (shutdown) — игнорируем.
            logger.debug(
                "drift_loop.trigger_for_chat: no running loop chat_id=%s",
                chat_id,
            )

    def shutdown(self) -> None:
        """Остановить idle scan. Direct fire-and-forget tasks не трогаем —
        они завершатся сами (после detector.detect)."""
        self._shutdown.set()
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()

    # ------------------------------------------------------------------
    # Internal — flags
    # ------------------------------------------------------------------

    class _Flags:
        __slots__ = ("enabled", "detect_enabled", "draft_enabled")

        def __init__(
            self, enabled: bool, detect_enabled: bool, draft_enabled: bool
        ) -> None:
            self.enabled = enabled
            self.detect_enabled = detect_enabled
            self.draft_enabled = draft_enabled

        def __repr__(self) -> str:
            return (
                f"_Flags(enabled={self.enabled}, "
                f"detect_enabled={self.detect_enabled}, "
                f"draft_enabled={self.draft_enabled})"
            )

    async def _get_flags(self) -> "_Flags":
        """Прочитать 3 PlatformSetting-флага с TTL-кешем 5 секунд.

        Если settings_service.get упал (БД недоступна, ключа нет) — fail-open:
        считаем, что всё включено (поведение не меняется для уже работающих
        инсталляций без флагов).
        """
        now = time.monotonic()
        if self._flags_cache is not None:
            enabled, detect_enabled, draft_enabled, cached_at = self._flags_cache
            if now - cached_at < _FLAG_CACHE_TTL_SECONDS:
                return DriftLoop._Flags(enabled, detect_enabled, draft_enabled)

        from app.services.settings_service import settings_service

        async def _fetch_flag(name: str, default: bool) -> bool:
            try:
                v = await settings_service.get(name)
            except KeyError:
                return default
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "drift_loop._get_flags: settings_service.get(%s) failed: %s",
                    name,
                    exc,
                )
                return default
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "on")
            if isinstance(v, (int, float)):
                return bool(v)
            return default

        enabled, detect_enabled, draft_enabled = await asyncio.gather(
            _fetch_flag("drift.enabled", True),
            _fetch_flag("drift.detect_enabled", True),
            _fetch_flag("drift.draft_enabled", True),
        )

        self._flags_cache = (
            enabled,
            detect_enabled,
            draft_enabled,
            now,
        )
        return DriftLoop._Flags(enabled, detect_enabled, draft_enabled)

    def invalidate_flags(self) -> None:
        """Сбросить кеш флагов (вызывается при изменении PlatformSetting)."""
        self._flags_cache = None

    # ------------------------------------------------------------------
    # Internal — detect / publish
    # ------------------------------------------------------------------

    async def _publish(
        self,
        chat_id: str,
        *,
        phase: DriftPhase,
        started_at=None,
        finished_at=None,
        message: str | None = None,
        drift_hints_count: int | None = None,
        draft_ops_count: int | None = None,
        draft_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Опубликовать drift-статус (если есть status_bus).

        Все ошибки шины тихо глотаются — она best-effort.
        """
        if self.status_bus is None:
            return
        try:
            await self.status_bus.publish(
                chat_id,
                DriftStatus(
                    chat_id=chat_id,
                    phase=phase,
                    started_at=started_at,
                    finished_at=finished_at,
                    published_at=_now(),
                    message=message,
                    drift_hints_count=drift_hints_count,
                    draft_ops_count=draft_ops_count,
                    draft_summary=draft_summary,
                    error=error,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift_loop._publish: status_bus failed chat_id=%s: %s",
                chat_id,
                exc,
            )

    async def _run_detect(self, chat_id: str) -> None:
        flags = await self._get_flags()
        started_at = _now()
        await self._publish(
            chat_id,
            phase=DriftPhase.DETECTING,
            started_at=started_at,
            message=_DETECTING_MESSAGE,
        )

        try:
            hints = await self.detector.detect(chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "drift_loop._run_detect: detector failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            await self._publish(
                chat_id,
                phase=DriftPhase.ERROR,
                started_at=started_at,
                finished_at=_now(),
                error=str(exc),
            )
            return

        if not hints:
            await self._publish(
                chat_id,
                phase=DriftPhase.IDLE,
                started_at=started_at,
                finished_at=_now(),
                message=None,
            )
            try:
                await self.redis.srem(_DIRTY_SET_KEY, chat_id)
            except Exception:  # noqa: BLE001
                pass
            return

        # Если draft отключён глобально — не запускаем drafter.
        if not flags.draft_enabled:
            logger.info(
                "drift_loop._run_detect: chat_id=%s produced %d hints "
                "(draft disabled, skip)",
                chat_id,
                len(hints),
            )
            await self._publish(
                chat_id,
                phase=DriftPhase.IDLE,
                started_at=started_at,
                finished_at=_now(),
                message=f"Найдено {len(hints)} подсказок (auto-draft отключён)",
                drift_hints_count=len(hints),
            )
            try:
                await self.redis.srem(_DIRTY_SET_KEY, chat_id)
            except Exception:  # noqa: BLE001
                pass
            return

        # Phase 3: запустить CampaignStateDrafter (если задан).
        await self._publish(
            chat_id,
            phase=DriftPhase.DRAFTING,
            started_at=_now(),
            message=_DRAFTING_MESSAGE,
            drift_hints_count=len(hints),
        )

        if self.drafter is None:
            logger.info(
                "drift_loop._run_detect: chat_id=%s produced %d hints "
                "(drafter not configured, skip)",
                chat_id,
                len(hints),
            )
            await self._publish(
                chat_id,
                phase=DriftPhase.IDLE,
                started_at=started_at,
                finished_at=_now(),
                drift_hints_count=len(hints),
            )
            try:
                await self.redis.srem(_DIRTY_SET_KEY, chat_id)
            except Exception:  # noqa: BLE001
                pass
            return

        draft: dict[str, Any] | None = None
        try:
            draft = await self.drafter.plan_draft(chat_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "drift_loop._run_detect: drafter failed chat_id=%s: %s",
                chat_id,
                exc,
            )
            await self._publish(
                chat_id,
                phase=DriftPhase.ERROR,
                started_at=started_at,
                finished_at=_now(),
                drift_hints_count=len(hints),
                error=str(exc),
            )
            try:
                await self.redis.srem(_DIRTY_SET_KEY, chat_id)
            except Exception:  # noqa: BLE001
                pass
            return

        # Убираем чат из dirty set — direct trigger его уже обработал.
        try:
            await self.redis.srem(_DIRTY_SET_KEY, chat_id)
        except Exception:  # noqa: BLE001
            pass

        if draft:
            state_patch = draft.get("state_patch") or []
            ops_count = len(state_patch) if isinstance(state_patch, list) else 0
            summary = draft.get("summary") if isinstance(draft, dict) else None
            preview = _build_draft_preview(
                state_patch if isinstance(state_patch, list) else [],
                summary if isinstance(summary, str) else "",
            )
            await self._publish(
                chat_id,
                phase=DriftPhase.DRAFT_READY,
                started_at=started_at,
                finished_at=_now(),
                drift_hints_count=len(hints),
                draft_ops_count=ops_count,
                draft_summary=preview,
            )
        else:
            # Drafter вернул None (нет смысла что-то менять) — тихо уходим в idle.
            await self._publish(
                chat_id,
                phase=DriftPhase.IDLE,
                started_at=started_at,
                finished_at=_now(),
                drift_hints_count=len(hints),
            )

    async def run_idle_scan(self) -> None:
        """Каждые idle_scan_period_seconds сканирует drift:dirty и запускает detect."""
        while not self._shutdown.is_set():
            # Если флаги выключены — не дёргаем dirty-сет вообще.
            flags = await self._get_flags()
            if not flags.enabled or not flags.detect_enabled:
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self.idle_scan_period_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            try:
                dirty_ids = await self.redis.smembers(_DIRTY_SET_KEY)
            except Exception as exc:  # noqa: BLE001
                logger.warning("drift_loop.run_idle_scan: SMEMBERS failed: %s", exc)
                dirty_ids = set()

            for chat_id in list(dirty_ids):
                if self._shutdown.is_set():
                    break
                try:
                    await self.trigger_for_chat(chat_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "drift_loop.run_idle_scan: trigger failed chat_id=%s: %s",
                        chat_id,
                        exc,
                    )

            # Прерываемый sleep.
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self.idle_scan_period_seconds,
                )
            except asyncio.TimeoutError:
                pass
