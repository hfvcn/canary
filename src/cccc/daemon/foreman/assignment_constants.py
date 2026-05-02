"""Shared constants for Foreman assignment orchestration."""

from __future__ import annotations


TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_DEFERRED = "deferred"
SINGLE_WRITER_REASON = "single_writer_active"
EXTERNAL_PRESSURE_REASON = "external_workflow_pressure"
ORCHESTRATOR_SERVICE_ACTOR = "service:workflow_orchestrator"
PROMPT_ISSUES_KEY = "prompt_issues"
RECOMMENDED_TESTS_KEY = "recommended_tests"
FORBIDDEN_FLOWS_KEY = "forbidden_flows"
