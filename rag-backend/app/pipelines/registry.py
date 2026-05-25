from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import types
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared_contracts.models import PipelineContext, PipelineResult


logger = logging.getLogger(__name__)

ExecuteCallable = Callable[[PipelineContext], Awaitable[PipelineResult]]


@dataclass(frozen=True)
class PipelineMetadata:
    pipeline_id: str
    domain: str
    version: str
    description: str
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineRunner:
    metadata: PipelineMetadata
    execute: ExecuteCallable
    source_hash: str

    async def run(self, context: PipelineContext) -> PipelineResult:
        result = await self.execute(context)
        if not isinstance(result, PipelineResult):
            result = PipelineResult.model_validate(result)
        missing = [key for key in self.metadata.output_keys if key not in result.metadata and key != "content"]
        if missing:
            logger.warning("Pipeline result is missing declared output keys: pipeline=%s missing=%s", self.metadata.pipeline_id, missing)
        return result


class PipelineRegistry:
    def __init__(self, pipelines_path: str) -> None:
        self.pipelines_path = Path(pipelines_path)
        self._lock = asyncio.Lock()
        self._runners: dict[str, dict[str, PipelineRunner]] = {}
        self._active_versions: dict[str, str] = {}
        self._fingerprints: dict[Path, str] = {}

    async def load_all(self) -> None:
        runners: list[PipelineRunner] = []
        fingerprints: dict[Path, str] = {}
        for metadata_path in sorted(self.pipelines_path.glob("*/*.yaml")):
            try:
                runner = _load_pipeline(metadata_path)
            except Exception:
                logger.error("Failed to load pipeline: %s", metadata_path, exc_info=True)
                continue
            runners.append(runner)
            impl_path = metadata_path.with_name("impl.py")
            fingerprints[metadata_path] = _file_hash(metadata_path)
            fingerprints[impl_path] = _file_hash(impl_path)

        async with self._lock:
            next_runners = {pipeline_id: dict(versions) for pipeline_id, versions in self._runners.items()}
            active_versions = dict(self._active_versions)
            for runner in runners:
                pipeline_id = runner.metadata.pipeline_id
                next_runners.setdefault(pipeline_id, {})[runner.metadata.version] = runner
                active_versions[pipeline_id] = runner.metadata.version
                logger.info("Pipeline loaded: id=%s version=%s domain=%s", pipeline_id, runner.metadata.version, runner.metadata.domain)
            self._runners = next_runners
            self._active_versions = active_versions
            self._fingerprints = fingerprints

    async def reload_if_changed(self) -> bool:
        current = _fingerprint_tree(self.pipelines_path)
        async with self._lock:
            if current == self._fingerprints:
                return False
        await self.load_all()
        return True

    async def run(self, pipeline_id: str, context: PipelineContext, version: str | None = None) -> PipelineResult:
        runner = await self.get_runner(pipeline_id, version)
        if runner is None:
            raise KeyError(f"Pipeline not found: {pipeline_id}@{version or 'active'}")
        return await runner.run(context)

    async def get_runner(self, pipeline_id: str, version: str | None = None) -> PipelineRunner | None:
        async with self._lock:
            versions = self._runners.get(pipeline_id)
            if not versions:
                return None
            selected_version = version or self._active_versions.get(pipeline_id)
            runner = versions.get(selected_version) if selected_version else None
            return runner or versions.get(self._active_versions.get(pipeline_id, ""))

    async def snapshot_versions(self) -> dict[str, str]:
        async with self._lock:
            return dict(self._active_versions)

    async def list_by_domain(self, domain: str | None) -> list[PipelineRunner]:
        async with self._lock:
            active: list[PipelineRunner] = []
            for pipeline_id, version in self._active_versions.items():
                runner = self._runners.get(pipeline_id, {}).get(version)
                if runner is not None and (domain is None or runner.metadata.domain == domain):
                    active.append(runner)
            return sorted(active, key=lambda runner: runner.metadata.pipeline_id)


class PipelineHotReloader:
    def __init__(self, registry: PipelineRegistry, interval_seconds: float, debounce_seconds: float) -> None:
        self.registry = registry
        self.interval_seconds = interval_seconds
        self.debounce_seconds = debounce_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.registry.load_all()
        self._task = asyncio.create_task(self._watch(), name="pipeline-hot-reload")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _watch(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                pass
            if self._stop.is_set():
                return
            try:
                changed = await self.registry.reload_if_changed()
                if changed:
                    await asyncio.sleep(self.debounce_seconds)
                    await self.registry.reload_if_changed()
                    logger.info("Pipeline registry hot-reloaded.")
            except Exception:
                logger.error("Pipeline hot-reload failed; keeping previous registry.", exc_info=True)


def _load_pipeline(metadata_path: Path) -> PipelineRunner:
    impl_path = metadata_path.with_name("impl.py")
    with metadata_path.open("r", encoding="utf-8") as metadata_file:
        payload: dict[str, Any] = yaml.safe_load(metadata_file) or {}

    contract = payload.get("contract") or {}
    metadata = PipelineMetadata(
        pipeline_id=str(payload["id"]),
        domain=str(payload["domain"]),
        version=str(payload["version"]),
        description=str(payload.get("description", "")),
        input_keys=[str(value) for value in contract.get("input_keys", [])],
        output_keys=[str(value) for value in contract.get("output_keys", [])],
    )
    execute = _load_execute(metadata, impl_path)
    return PipelineRunner(metadata=metadata, execute=execute, source_hash=_file_hash(metadata_path) + _file_hash(impl_path))


def _load_execute(metadata: PipelineMetadata, impl_path: Path) -> ExecuteCallable:
    module_name = f"pipeline_{metadata.domain}_{metadata.pipeline_id}_{metadata.version}_{hashlib.sha256(str(impl_path).encode()).hexdigest()[:8]}"
    if not impl_path.exists():
        raise ValueError(f"Cannot load pipeline module: {impl_path}")
    module = types.ModuleType(module_name)
    module.__file__ = str(impl_path)
    source = impl_path.read_text(encoding="utf-8")
    exec(compile(source, str(impl_path), "exec"), module.__dict__)
    execute = getattr(module, "execute", None)
    if execute is None or not inspect.iscoroutinefunction(execute):
        raise ValueError(f"Pipeline {impl_path} must define async execute(context)")
    return execute


def _fingerprint_tree(path: Path) -> dict[Path, str]:
    fingerprints: dict[Path, str] = {}
    for file_path in sorted([*path.glob("*/*.yaml"), *path.glob("*/impl.py")]):
        fingerprints[file_path] = _file_hash(file_path)
    return fingerprints


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()
