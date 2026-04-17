import unittest

from cccc.contracts.v1.ipc import DaemonResponse
from cccc.contracts.v1.ralph_ipc import (
    FATAL_IPC_VALIDATION_CODES,
    WORKFLOW_PLAN_VALIDATION_FAILED,
    IpcValidationError,
    RalphRegisterResponse,
)


class TestRalphIpcValidationErrors(unittest.TestCase):
    def test_ipc_validation_error_round_trip(self) -> None:
        payload = {
            "code": "E_DEP_CYCLE",
            "severity": "error",
            "message": "dependency cycle detected",
            "task_ids": ["T1", "T2"],
            "evidence": {"cycle": ["T1", "T2", "T1"]},
        }

        error = IpcValidationError.model_validate(payload)
        restored = IpcValidationError.model_validate(error.model_dump())

        # Core fields round-trip exactly
        self.assertEqual(restored.code, payload["code"])
        self.assertEqual(restored.severity, payload["severity"])
        self.assertEqual(restored.message, payload["message"])
        self.assertEqual(restored.task_ids, payload["task_ids"])
        self.assertEqual(restored.evidence, payload["evidence"])
        # W4 metadata defaults are preserved through round-trip
        self.assertEqual(restored.confidence, "opaque")
        self.assertEqual(restored.source, "")
        self.assertEqual(restored.action_owner, "unknown")
        self.assertEqual(restored.worker_relevance, "none")

    def test_ralph_register_response_defaults_are_empty(self) -> None:
        response = RalphRegisterResponse(
            workflow_id="wf-1",
            registered_count=2,
            submitted_count=1,
        )

        self.assertEqual(response.ready_task_ids, [])
        self.assertEqual(response.validation_errors, [])
        self.assertEqual(response.validation_warnings, [])
        self.assertEqual(response.validation_hints, [])
        self.assertFalse(response.plan_validation_failed_event_emitted)

    def test_ralph_register_response_backward_compat_old_payload_parses(self) -> None:
        restored = RalphRegisterResponse.model_validate(
            {
                "workflow_id": "wf-1",
                "registered_count": 1,
                "submitted_count": 1,
                "ready_task_ids": ["T1"],
            }
        )

        self.assertEqual(restored.workflow_id, "wf-1")
        self.assertEqual(restored.ready_task_ids, ["T1"])
        self.assertEqual(restored.validation_errors, [])
        self.assertEqual(restored.validation_warnings, [])
        self.assertEqual(restored.validation_hints, [])
        self.assertFalse(restored.plan_validation_failed_event_emitted)

    def test_daemon_response_accepts_typed_ralph_register_payload(self) -> None:
        payload = RalphRegisterResponse(
            workflow_id="wf-1",
            registered_count=1,
            submitted_count=0,
            validation_errors=[
                IpcValidationError(
                    code="E_DUPLICATE_TASK_ID",
                    severity="error",
                    message="duplicate task id",
                )
            ],
        ).model_dump()

        response = DaemonResponse(ok=True, result=payload)

        self.assertTrue(response.ok)
        self.assertEqual(response.result["workflow_id"], "wf-1")
        self.assertEqual(response.result["validation_errors"][0]["code"], "E_DUPLICATE_TASK_ID")

    def test_validation_constants_are_importable(self) -> None:
        self.assertEqual(WORKFLOW_PLAN_VALIDATION_FAILED, "workflow.plan_validation_failed")
        self.assertIn("E_DEP_CYCLE", FATAL_IPC_VALIDATION_CODES)
        self.assertIn("E_SEMANTIC_PROVIDER_UNAVAILABLE", FATAL_IPC_VALIDATION_CODES)


if __name__ == "__main__":
    unittest.main()
