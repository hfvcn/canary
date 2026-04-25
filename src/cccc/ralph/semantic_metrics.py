"""Semantic metrics for advisory-to-gate upgrades."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Literal, Optional

DEFAULT_METRICS_PATH = Path(".ralph/semantic_metrics.jsonl")
METRICS_PATH_ENV_VAR = "CCCC_RALPH_METRICS_PATH"
DEFAULT_GATE_THRESHOLD = 0.05
DEFAULT_MIN_SAMPLES = 50
CONFIDENCE_LEVELS = ("exact", "best_effort", "opaque")
ACTUAL_OUTCOMES = ("true_positive", "false_positive", "missed")
PREDICTED_OUTCOMES = ("true_positive", "false_positive")

ConfidenceLevel = Literal["exact", "best_effort", "opaque"]
ActualOutcome = Literal["true_positive", "false_positive", "missed"]


@dataclass(frozen=True)
class GateReadiness:
    rule_code: str
    confidence_filter: Optional[str]
    total_predictions: int
    true_positives: int
    false_positives: int
    false_positive_rate: float
    accuracy: float
    sample_size_sufficient: bool
    gate_ready: bool


def resolve_metrics_path(
    metrics_path: Path | str | None = None,
    project_root: Path | None = None,
) -> Path:
    if metrics_path is not None:
        candidate = Path(metrics_path)
        if candidate.is_absolute() or project_root is None:
            return candidate
        return Path(project_root) / candidate

    env_override = os.environ.get(METRICS_PATH_ENV_VAR)
    if env_override:
        return Path(env_override)

    if project_root is not None:
        return Path(project_root) / DEFAULT_METRICS_PATH

    return DEFAULT_METRICS_PATH


def _require_allowed(name: str, value: str, allowed: Iterable[str]) -> str:
    allowed_values = tuple(allowed)
    if value not in allowed_values:
        joined = ", ".join(allowed_values)
        raise ValueError(f"{name} must be one of: {joined}")
    return value


def _iter_records(metrics_path: Path) -> Iterator[Dict[str, Any]]:
    if not metrics_path.exists():
        return

    with metrics_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def _filter_records(
    rule_code: str,
    confidence_filter: str | None,
    metrics_path: Path,
) -> list[Dict[str, Any]]:
    return [
        record
        for record in _iter_records(metrics_path)
        if record.get("rule") == rule_code
        and (confidence_filter is None or record.get("confidence") == confidence_filter)
    ]


def _count_predictions(records: Iterable[Dict[str, Any]]) -> tuple[int, int, int]:
    true_positives = 0
    false_positives = 0
    total_predictions = 0
    for record in records:
        outcome = record.get("actual_outcome")
        if outcome not in PREDICTED_OUTCOMES:
            continue
        total_predictions += 1
        if outcome == "true_positive":
            true_positives += 1
            continue
        false_positives += 1
    return total_predictions, true_positives, false_positives


def _format_readiness_line(readiness: GateReadiness, label: str) -> str:
    return (
        f"  {label:<12} total={readiness.total_predictions:>3} "
        f"tp={readiness.true_positives:>3} fp={readiness.false_positives:>3} "
        f"fpr={readiness.false_positive_rate:.1%} "
        f"accuracy={readiness.accuracy:.1%} "
        f"ready={readiness.gate_ready}"
    )


def record_semantic_outcome(
    plan_name: str,
    task_id: str,
    rule_code: str,
    predicted_severity: str,
    confidence: ConfidenceLevel,
    actual_outcome: ActualOutcome,
    metrics_path: Path | str | None = None,
    *,
    project_root: Path | None = None,
    evidence: Dict[str, Any] | None = None,
) -> None:
    """Append one semantic outcome record to the audit log."""
    metrics_file = resolve_metrics_path(metrics_path, project_root)
    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "plan": plan_name,
        "task": task_id,
        "rule": rule_code,
        "predicted_severity": predicted_severity,
        "confidence": _require_allowed("confidence", confidence, CONFIDENCE_LEVELS),
        "actual_outcome": _require_allowed("actual_outcome", actual_outcome, ACTUAL_OUTCOMES),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if evidence is not None:
        record["evidence"] = evidence
    with metrics_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def compute_gate_readiness(
    rule_code: str,
    threshold: float,
    confidence_filter: str | None = None,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    metrics_path: Path | str | None = None,
    *,
    project_root: Path | None = None,
) -> GateReadiness:
    """Compute gate readiness from recorded outcomes."""
    if confidence_filter is not None:
        _require_allowed("confidence_filter", confidence_filter, CONFIDENCE_LEVELS)

    records = _filter_records(
        rule_code=rule_code,
        confidence_filter=confidence_filter,
        metrics_path=resolve_metrics_path(metrics_path, project_root),
    )
    total_predictions, true_positives, false_positives = _count_predictions(records)
    false_positive_rate = false_positives / total_predictions if total_predictions else 0.0
    accuracy = true_positives / total_predictions if total_predictions else 0.0
    sample_size_sufficient = total_predictions >= min_samples
    gate_ready = sample_size_sufficient and false_positive_rate < threshold
    return GateReadiness(
        rule_code=rule_code,
        confidence_filter=confidence_filter,
        total_predictions=total_predictions,
        true_positives=true_positives,
        false_positives=false_positives,
        false_positive_rate=false_positive_rate,
        accuracy=accuracy,
        sample_size_sufficient=sample_size_sufficient,
        gate_ready=gate_ready,
    )


def format_gate_report(
    metrics_path: Path | str | None = None,
    *,
    project_root: Path | None = None,
) -> str:
    """Format a gate-readiness report for all tracked rules."""
    metrics_file = resolve_metrics_path(metrics_path, project_root)
    records = list(_iter_records(metrics_file))
    if not records:
        return "No semantic metrics recorded yet."

    rule_codes = sorted({record["rule"] for record in records if "rule" in record})
    lines = [
        "Ralph semantic gate readiness:",
        (
            f"Default threshold={DEFAULT_GATE_THRESHOLD:.0%}, "
            f"min_samples={DEFAULT_MIN_SAMPLES}"
        ),
        "",
    ]
    for rule_code in rule_codes:
        overall = compute_gate_readiness(
            rule_code,
            DEFAULT_GATE_THRESHOLD,
            min_samples=DEFAULT_MIN_SAMPLES,
            metrics_path=metrics_file,
        )
        lines.append(rule_code)
        lines.append(_format_readiness_line(overall, "all"))
        for confidence in CONFIDENCE_LEVELS:
            readiness = compute_gate_readiness(
                rule_code,
                DEFAULT_GATE_THRESHOLD,
                confidence_filter=confidence,
                min_samples=DEFAULT_MIN_SAMPLES,
                metrics_path=metrics_file,
            )
            lines.append(_format_readiness_line(readiness, confidence))
        lines.append("")

    return "\n".join(lines).rstrip()


__all__ = [
    "DEFAULT_METRICS_PATH",
    "GateReadiness",
    "compute_gate_readiness",
    "format_gate_report",
    "record_semantic_outcome",
    "resolve_metrics_path",
]
