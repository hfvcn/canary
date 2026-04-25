"""Contract validation rules — provider/consumer matching and schema compatibility.

Extracted from validator.py as a pure refactor (RO-31).
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from ..models import (
    Contract,
    Plan,
    ValidationIssue,
)


SCHEMA_TYPE_KEY = "type"
SCHEMA_FORMAT_KEY = "format"
SCHEMA_PROPERTIES_KEY = "properties"
SCHEMA_ITEMS_KEY = "items"
SCHEMA_REQUIRED_KEY = "required"


# ---------------------------------------------------------------------------
# 5. Contract matching (provides / consumes)
# ---------------------------------------------------------------------------

def _check_contracts(plan: Plan) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []

    # Build provider map: name -> (task_id, contract)
    providers: Dict[str, List[Tuple[str, Contract]]] = {}
    for t in plan.tasks:
        for c in t.provides:
            providers.setdefault(c.name, []).append((t.id, c))

    task_ids = {task.id for task in plan.tasks}

    # Check consumers
    for t in plan.tasks:
        for c in t.consumes:
            provider_matches = _find_matching_providers(c, providers)
            if c.name not in providers:
                issues.append(ValidationIssue(
                    code="E_CONSUMER_WITHOUT_PROVIDER",
                    severity="error",
                    message=f"task '{t.id}' consumes '{c.name}' but no task provides it",
                    task_ids=[t.id],
                    evidence={"contract_name": c.name},
                ))
            # Check from_task reference
            if c.from_task:
                if c.from_task not in task_ids:
                    issues.append(ValidationIssue(
                        code="E_CONSUMER_FROM_UNKNOWN",
                        severity="error",
                        message=f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'",
                        task_ids=[t.id],
                        evidence={"contract_name": c.name, "from_task": c.from_task},
                    ))
                    continue

            if _should_warn_on_contract_schema_mismatch(c, provider_matches):
                provider_task_ids = [task_id for task_id, _ in provider_matches]
                issues.append(ValidationIssue(
                    code="W_CONTRACT_SCHEMA_MISMATCH",
                    severity="warning",
                    message=f"task '{t.id}' consumes '{c.name}' with an incompatible schema hint",
                    task_ids=[t.id, *provider_task_ids],
                    evidence={
                        "contract_name": c.name,
                        "consumer_schema_hint": c.schema_hint,
                        "provider_schema_hints": {
                            task_id: provider.schema_hint for task_id, provider in provider_matches
                        },
                    },
                ))

    # Unused providers (hint, not error)
    consumed_names = set()
    for t in plan.tasks:
        for c in t.consumes:
            consumed_names.add(c.name)

    for name, provider_list in providers.items():
        if name not in consumed_names:
            task_ids = [tid for tid, _ in provider_list]
            issues.append(ValidationIssue(
                code="W_PROVIDER_UNUSED",
                severity="hint",
                message=f"contract '{name}' is provided but never consumed",
                task_ids=task_ids,
                evidence={"contract_name": name},
            ))

    return issues


def _check_contract_verification_coverage(plan: Plan) -> List[ValidationIssue]:
    """Hint when a consumer's verification doesn't test the provider's interface."""
    issues: List[ValidationIssue] = []
    task_map = {task.id: task for task in plan.tasks}

    for task in plan.tasks:
        if task.verification is None:
            continue
        command = task.verification.command
        if not command.strip():
            continue

        for contract in task.consumes:
            if contract.from_task is None:
                continue
            provider = task_map.get(contract.from_task)
            if provider is None or not provider.claimed_paths:
                continue
            if _command_mentions_any_path(command, provider.claimed_paths):
                continue

            issues.append(ValidationIssue(
                code="W_INTEGRATION_INTERFACE_MISMATCH",
                severity="hint",
                message=f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' "
                        f"but verification does not reference any of {contract.from_task}'s paths",
                task_ids=[task.id, contract.from_task],
                evidence={
                    "contract": contract.name,
                    "consumer": task.id,
                    "provider": contract.from_task,
                    "provider_paths": provider.claimed_paths,
                },
            ))

    return issues


# ---------------------------------------------------------------------------
# 7. Contract <-> dependency alignment
# ---------------------------------------------------------------------------

def _check_contract_dep_alignment(plan: Plan) -> List[ValidationIssue]:
    """Check that consumes edges align with depends_on edges."""
    issues: List[ValidationIssue] = []
    task_map = {t.id: t for t in plan.tasks}

    for t in plan.tasks:
        dep_set = set(t.depends_on)
        consume_sources = set()
        for c in t.consumes:
            if c.from_task:
                consume_sources.add(c.from_task)

        # consumes from a task not in depends_on
        for src in consume_sources:
            if src not in dep_set and src in task_map:
                issues.append(ValidationIssue(
                    code="W_CONSUME_WITHOUT_DEP",
                    severity="warning",
                    message=f"task '{t.id}' consumes from '{src}' but does not depend on it",
                    task_ids=[t.id, src],
                ))

        # depends_on a task that provides something, but no consume declared
        if t.consumes:  # only check if task uses contracts at all
            for dep_id in t.depends_on:
                dep_task = task_map.get(dep_id)
                if dep_task and dep_task.provides and dep_id not in consume_sources:
                    issues.append(ValidationIssue(
                        code="W_DEP_WITHOUT_CONSUME",
                        severity="hint",
                        message=f"task '{t.id}' depends on '{dep_id}' which provides contracts, "
                                f"but does not consume any of them",
                        task_ids=[t.id, dep_id],
                    ))

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_matching_providers(
    consumer: Contract,
    providers: Dict[str, List[Tuple[str, Contract]]],
) -> List[Tuple[str, Contract]]:
    matches = providers.get(consumer.name, [])
    if consumer.from_task is None:
        return matches
    return [(task_id, contract) for task_id, contract in matches if task_id == consumer.from_task]


def _should_warn_on_contract_schema_mismatch(
    consumer: Contract,
    provider_matches: List[Tuple[str, Contract]],
) -> bool:
    if not isinstance(consumer.schema_hint, dict):
        return False
    if not provider_matches:
        return False

    checked_provider = False
    for _, provider in provider_matches:
        if not isinstance(provider.schema_hint, dict):
            continue
        checked_provider = True
        if _contract_schema_hints_compatible(provider.schema_hint, consumer.schema_hint):
            return False
    return checked_provider


def _contract_schema_hints_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    if not isinstance(provider_schema, dict) or not isinstance(consumer_schema, dict):
        return True

    if not _schema_scalar_compatible(provider_schema, consumer_schema):
        return False
    if not _schema_properties_compatible(provider_schema, consumer_schema):
        return False
    if not _schema_items_compatible(provider_schema, consumer_schema):
        return False
    return _schema_required_compatible(provider_schema, consumer_schema)


def _schema_scalar_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_type = provider_schema.get(SCHEMA_TYPE_KEY)
    consumer_type = consumer_schema.get(SCHEMA_TYPE_KEY)
    if (
        provider_type is not None
        and consumer_type is not None
        and provider_type != consumer_type
    ):
        return False

    provider_format = provider_schema.get(SCHEMA_FORMAT_KEY)
    consumer_format = consumer_schema.get(SCHEMA_FORMAT_KEY)
    if provider_format is None or consumer_format is None:
        return True
    return provider_format == consumer_format


def _schema_properties_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_properties = provider_schema.get(SCHEMA_PROPERTIES_KEY)
    consumer_properties = consumer_schema.get(SCHEMA_PROPERTIES_KEY)
    if not isinstance(provider_properties, dict) or not isinstance(consumer_properties, dict):
        return True

    for property_name, consumer_property in consumer_properties.items():
        if property_name not in provider_properties:
            return False
        provider_property = provider_properties[property_name]
        if not _contract_schema_hints_compatible(provider_property, consumer_property):
            return False
    return True


def _schema_items_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    provider_items = provider_schema.get(SCHEMA_ITEMS_KEY)
    consumer_items = consumer_schema.get(SCHEMA_ITEMS_KEY)
    if provider_items is None or consumer_items is None:
        return True
    return _contract_schema_hints_compatible(provider_items, consumer_items)


def _schema_required_compatible(
    provider_schema: Dict[str, Any],
    consumer_schema: Dict[str, Any],
) -> bool:
    consumer_required = consumer_schema.get(SCHEMA_REQUIRED_KEY)
    if not isinstance(consumer_required, list):
        return True

    provider_required = provider_schema.get(SCHEMA_REQUIRED_KEY)
    provider_required_set = set(provider_required) if isinstance(provider_required, list) else set()
    provider_properties = provider_schema.get(SCHEMA_PROPERTIES_KEY)
    provider_property_names = set(provider_properties) if isinstance(provider_properties, dict) else set()

    return all(
        isinstance(field_name, str)
        and (field_name in provider_required_set or field_name in provider_property_names)
        for field_name in consumer_required
    )


def _command_mentions_any_path(command: str, claimed_paths: List[str]) -> bool:
    return any(path and path in command for path in claimed_paths)
