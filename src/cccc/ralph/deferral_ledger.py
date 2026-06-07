from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import pathlib

import yaml

DEFAULT_LEDGER_PATH = pathlib.Path("todo/deferral-ledger.yaml")
STATUS_DEFERRED = "deferred"
STATUS_ESCALATED = "escalated"
STATUS_CLEARED = "cleared"
_VALID_STATUSES = frozenset({STATUS_DEFERRED, STATUS_ESCALATED, STATUS_CLEARED})


def begin_round(
    ledger_path: str | pathlib.Path = DEFAULT_LEDGER_PATH,
    version: str = "",
    deferred_ids: Iterable[str] = (),
) -> dict[str, dict[str, int | str]]:
    normalized_version = _normalize_version(version)
    ledger = _read_ledger(ledger_path)
    deferred = _normalize_issue_ids(deferred_ids)
    updated = {
        issue_id: _next_entry(
            _entry_from_raw(ledger.get(issue_id), issue_id),
            normalized_version,
            issue_id in deferred,
        )
        for issue_id in sorted(set(ledger) | deferred)
    }
    _write_ledger(ledger_path, updated)
    return updated


def record_deferral(
    ledger_path: str | pathlib.Path = DEFAULT_LEDGER_PATH,
    issue_id: str = "",
    version: str = "",
) -> dict[str, int | str]:
    normalized_issue_id = _normalize_issue_id(issue_id)
    ledger = begin_round(ledger_path, version, {normalized_issue_id})
    return ledger[normalized_issue_id]


def escalated_blockers(
    ledger_path: str | pathlib.Path = DEFAULT_LEDGER_PATH,
    evidence_fn: Callable[[str], bool] | None = None,
) -> list[str]:
    ledger = _read_ledger(ledger_path, missing_ok=True)
    if not ledger:
        return []
    checker = evidence_fn or (lambda _issue_id: False)
    return sorted(
        issue_id
        for issue_id, raw_entry in ledger.items()
        if _entry_from_raw(raw_entry, issue_id)["status"] == STATUS_ESCALATED
        and not checker(issue_id)
    )


def clear_deferral(
    ledger_path: str | pathlib.Path = DEFAULT_LEDGER_PATH,
    issue_id: str = "",
    version: str = "",
) -> dict[str, int | str]:
    normalized_issue_id = _normalize_issue_id(issue_id)
    normalized_version = _normalize_version(version)
    ledger = _read_ledger(ledger_path, missing_ok=True)
    current = _entry_from_raw(ledger.get(normalized_issue_id), normalized_issue_id)
    cleared = {
        **current,
        "streak_count": 0,
        "cleared_version": normalized_version,
        "status": STATUS_CLEARED,
    }
    ledger[normalized_issue_id] = cleared
    _write_ledger(ledger_path, ledger)
    return cleared


def _read_ledger(
    ledger_path: str | pathlib.Path,
    *,
    missing_ok: bool = False,
) -> dict[str, dict[str, int | str]]:
    path = pathlib.Path(ledger_path)
    if not path.is_file():
        return {} if missing_ok else {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"deferral ledger must be a mapping: {path}")
    return {str(issue_id): _entry_from_raw(entry, str(issue_id)) for issue_id, entry in raw.items()}


def _write_ledger(
    ledger_path: str | pathlib.Path,
    ledger: Mapping[str, Mapping[str, int | str]],
) -> None:
    path = pathlib.Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        issue_id: _entry_from_raw(entry, issue_id)
        for issue_id, entry in sorted(ledger.items())
    }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )


def _entry_from_raw(raw: object, issue_id: str) -> dict[str, int | str]:
    if raw is None:
        return _default_entry()
    if not isinstance(raw, Mapping):
        raise ValueError(f"deferral ledger entry must be a mapping: {issue_id}")
    status = str(raw.get("status") or STATUS_DEFERRED).strip()
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid deferral ledger status for {issue_id}: {status}")
    streak_count = _normalize_streak_count(raw.get("streak_count"), issue_id)
    return {
        "streak_count": streak_count,
        "last_deferred_version": str(raw.get("last_deferred_version") or "").strip(),
        "cleared_version": str(raw.get("cleared_version") or "").strip(),
        "status": status,
    }


def _default_entry() -> dict[str, int | str]:
    return {
        "streak_count": 0,
        "last_deferred_version": "",
        "cleared_version": "",
        "status": STATUS_DEFERRED,
    }


def _normalize_streak_count(value: object, issue_id: str) -> int:
    try:
        streak_count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid streak_count for {issue_id}: {value}") from exc
    if streak_count < 0:
        raise ValueError(f"invalid streak_count for {issue_id}: {value}")
    return streak_count


def _next_entry(
    current: Mapping[str, int | str],
    version: str,
    deferred_this_round: bool,
) -> dict[str, int | str]:
    status = str(current["status"])
    if not deferred_this_round:
        if status == STATUS_CLEARED:
            return {**current, "streak_count": 0}
        return {**current, "streak_count": 0, "status": STATUS_DEFERRED}
    if str(current["last_deferred_version"]) == version:
        return dict(current)
    prior_streak = 0 if status == STATUS_CLEARED else int(current["streak_count"])
    next_streak = 1 if prior_streak <= 0 else prior_streak + 1
    next_status = STATUS_ESCALATED if next_streak >= 2 else STATUS_DEFERRED
    return {
        **current,
        "streak_count": next_streak,
        "last_deferred_version": version,
        "status": next_status,
    }


def _normalize_issue_ids(issue_ids: Iterable[str]) -> set[str]:
    return {
        _normalize_issue_id(issue_id)
        for issue_id in issue_ids
        if str(issue_id or "").strip()
    }


def _normalize_issue_id(issue_id: str) -> str:
    normalized = str(issue_id or "").strip()
    if not normalized:
        raise ValueError("issue_id is required")
    return normalized


def _normalize_version(version: str) -> str:
    normalized = str(version or "").strip()
    if not normalized:
        raise ValueError("version is required")
    return normalized
