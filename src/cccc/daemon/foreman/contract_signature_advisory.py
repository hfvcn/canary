"""Advisory provider-source checks for contract signatures."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from ...contracts.v1.ralph_ipc import TaskRef
from ...ralph.contract_signatures import (
    contract_signature_map,
    extract_module_function_signatures,
    signature_mismatches,
)


logger = logging.getLogger("cccc.daemon.foreman.contract_signature_advisory")


@dataclass(frozen=True)
class SignatureAdvisoryContext:
    project_root: Path
    all_tasks: List[TaskRef]
    consumer_tasks: List[TaskRef]
    log_fn: Callable[[str], None] | None = None


ProviderMatch = Tuple[str, Dict[str, object], TaskRef]
ProviderIndex = Dict[str, List[ProviderMatch]]


@dataclass(frozen=True)
class ConsumerContractCheck:
    context: SignatureAdvisoryContext
    consumer: TaskRef
    contract: Dict[str, object]
    provider_index: ProviderIndex


@dataclass(frozen=True)
class ProviderSourceCheck:
    context: SignatureAdvisoryContext
    consumer_id: str
    contract: Dict[str, object]
    provider_id: str
    provider_task: TaskRef
    consumer_signatures: Dict[str, str]


def warn_on_contract_signature_source_mismatches(context: SignatureAdvisoryContext) -> None:
    """Log advisory warnings when provider source does not match consumer signatures."""
    provider_index = _build_provider_index(context.all_tasks)
    for consumer in context.consumer_tasks:
        for contract in consumer.consumes:
            _warn_for_consumer_contract(
                ConsumerContractCheck(context, consumer, contract, provider_index)
            )


def _warn_for_consumer_contract(check: ConsumerContractCheck) -> None:
    consumer_signatures = _read_contract_signatures(
        check.context,
        check.consumer.id,
        check.contract,
    )
    if not consumer_signatures:
        return
    matches = _matching_providers(check.contract, check.provider_index)
    if not matches:
        _emit(
            check.context,
            _warning_prefix(check.consumer.id, "", check.contract) + " provider not found",
        )
        return
    for provider_id, _, provider_task in matches:
        _warn_for_provider_source(
            ProviderSourceCheck(
                check.context,
                check.consumer.id,
                check.contract,
                provider_id,
                provider_task,
                consumer_signatures,
            )
        )


def _warn_for_provider_source(check: ProviderSourceCheck) -> None:
    source_signatures = _read_provider_source_signatures(
        check.context,
        check.provider_id,
        check.provider_task,
    )
    mismatches = signature_mismatches(source_signatures, check.consumer_signatures)
    if mismatches:
        prefix = _warning_prefix(check.consumer_id, check.provider_id, check.contract)
        _emit(check.context, f"{prefix} source signature mismatch: {mismatches}")


def _read_contract_signatures(
    context: SignatureAdvisoryContext,
    task_id: str,
    contract: Dict[str, object],
) -> Dict[str, str]:
    try:
        return contract_signature_map(contract)
    except TypeError as exc:
        _emit(context, _warning_prefix(task_id, "", contract) + f" invalid signatures: {exc}")
        return {}


def _read_provider_source_signatures(
    context: SignatureAdvisoryContext,
    provider_id: str,
    provider_task: TaskRef,
) -> Dict[str, str]:
    signatures: Dict[str, str] = {}
    source_paths = _provider_python_paths(context, provider_id, provider_task)
    for source_path in source_paths:
        signatures.update(_read_one_source(context, provider_id, source_path))
    if not source_paths:
        _emit(context, f"contract signature advisory: provider={provider_id} has no Python source")
    return signatures


def _read_one_source(
    context: SignatureAdvisoryContext,
    provider_id: str,
    source_path: Path,
) -> Dict[str, str]:
    try:
        return extract_module_function_signatures(source_path.read_text(encoding="utf-8"))
    except OSError as exc:
        _emit(context, f"contract signature advisory: provider={provider_id} read failed: {exc}")
        return {}
    except SyntaxError as exc:
        _emit(context, f"contract signature advisory: provider={provider_id} parse failed: {exc}")
        return {}


def _provider_python_paths(
    context: SignatureAdvisoryContext,
    provider_id: str,
    provider_task: TaskRef,
) -> List[Path]:
    paths: List[Path] = []
    for claimed_path in provider_task.claimed_paths:
        paths.extend(_python_paths_for_claim(context, provider_id, claimed_path))
    return paths


def _python_paths_for_claim(
    context: SignatureAdvisoryContext,
    provider_id: str,
    claimed_path: str,
) -> List[Path]:
    path = _resolve_claimed_path(context.project_root, claimed_path)
    if not _is_inside_project(context.project_root, path):
        _emit(context, f"contract signature advisory: provider={provider_id} path outside project")
        return []
    if path.is_file() and path.suffix == ".py":
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.py"))
    _emit(context, f"contract signature advisory: provider={provider_id} path missing: {claimed_path}")
    return []


def _build_provider_index(tasks: Iterable[TaskRef]) -> ProviderIndex:
    providers: ProviderIndex = {}
    for task in tasks:
        for contract in task.provides:
            name = str(contract.get("name") or "").strip()
            if name:
                providers.setdefault(name, []).append((task.id, contract, task))
    return providers


def _matching_providers(
    contract: Dict[str, object],
    provider_index: ProviderIndex,
) -> List[ProviderMatch]:
    name = str(contract.get("name") or "").strip()
    from_task = str(contract.get("from") or "").strip()
    matches = provider_index.get(name, [])
    if not from_task:
        return matches
    return [match for match in matches if match[0] == from_task]


def _warning_prefix(consumer_id: str, provider_id: str, contract: Dict[str, object]) -> str:
    name = str(contract.get("name") or "").strip()
    return (
        "contract signature advisory:"
        f" consumer={consumer_id} provider={provider_id or '<unknown>'} contract={name}"
    )


def _resolve_claimed_path(project_root: Path, claimed_path: str) -> Path:
    path = Path(claimed_path)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def _is_inside_project(project_root: Path, path: Path) -> bool:
    return path.is_relative_to(project_root.resolve())


def _emit(context: SignatureAdvisoryContext, message: str) -> None:
    logger.warning(message)
    if context.log_fn is not None:
        context.log_fn(f"[orchestrator] {message}")
