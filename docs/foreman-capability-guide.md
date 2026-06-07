# Ralph Capability Guide

## Plan Schema Fields

### Plan
- Path: `top level`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `schema_version` | `Optional` | `None` |  |
| `execution_engine` | `Optional` | `None` |  |
| `tasks` | `List` | `<factory list>` |  |
| `state` | `PlanState` | `<factory PlanState>` |  |
| `plan_scope` | `List` | `<factory list>` |  |
| `critical_entrypoints` | `List` | `<factory list>` |  |
| `critical_flows` | `List` | `<factory list>` |  |
| `forbidden_flows` | `List` | `<factory list>` |  |
| `finding_refs` | `List` | `<factory list>` |  |
| `registration_invariants` | `List` | `<factory list>` |  |
| `suppress_flows` | `List` | `<factory list>` |  |
| `batch_e2e_command` | `Optional` | `None` |  |
| `batch_e2e_timeout` | `int` | `300` |  |
| `required_issues` | `List` | `<factory list>` |  |
| `suppress_codes` | `List` | `<factory list>` |  |
| `suppress_instances` | `List` | `<factory list>` |  |
| `semantic_mode` | `str` | `'off'` |  |
| `auto_infer` | `bool` | `False` |  |

### TaskSpec
- Path: `tasks[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `str` | `(required)` |  |
| `title` | `str` | `''` |  |
| `role` | `Literal` | `'leaf'` |  |
| `type` | `Literal` | `'general'` |  |
| `depends_on` | `List` | `<factory list>` |  |
| `claimed_paths` | `List` | `<factory list>` |  |
| `awareness_paths` | `List` | `<factory list>` |  |
| `goal_behavior` | `str` | `''` |  |
| `acceptance_criteria` | `str` | `''` |  |
| `verification_mode` | `Literal` | `'ralph'` | ralph: shell command exit code. agent: Gemini reviews code + runs mock_tests. challenge: adversarial mode with attack payloads. |
| `verification` | `Optional` | `None` |  |
| `provides` | `List` | `<factory list>` | Task outputs as Contract objects ({name, kind, schema_hint}). |
| `consumes` | `List` | `<factory list>` | Task inputs from upstream as Contract objects ({name, from, kind}). |
| `addresses` | `List` | `<factory list>` |  |
| `failure_path` | `str` | `''` |  |
| `semantic` | `Optional` | `None` |  |
| `aegis` | `Optional` | `None` | Aegis execution discipline: intent, repair_track, retirement_track, baseline_refs, patch_shape_triage, compat_boundary, decision_review, drift_check. |
| `expected_input` | `Dict` | `<factory dict>` |  |
| `expected_output` | `Dict` | `<factory dict>` |  |
| `modules` | `Optional` | `None` |  |

### Verification
- Path: `tasks[].verification`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `level` | `Literal` | `(required)` |  |
| `command` | `str` | `''` |  |
| `checks` | `List` | `<factory list>` |  |
| `covers` | `VerificationCovers` | `<factory VerificationCovers>` |  |
| `expected_exit_code` | `int` | `0` |  |
| `cleanup_patterns` | `Optional` | `None` |  |
| `mock_tests` | `Optional` | `None` | Adversarial test cases for agent/challenge mode. Each MockTestCase has: name, input, expected_output, setup_command, verify_command, description. |

### CheckSpec
- Path: `tasks[].verification.checks[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | `(required)` |  |
| `command` | `str` | `(required)` |  |
| `required` | `bool` | `True` |  |
| `expected_exit_code` | `int` | `0` |  |
| `timeout` | `Optional` | `None` |  |

### VerificationCovers
- Path: `tasks[].verification.covers`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `tasks` | `List` | `<factory list>` |  |
| `paths` | `List` | `<factory list>` |  |
| `flows` | `List` | `<factory list>` |  |

### MockTestCase
- Path: `tasks[].verification.mock_tests[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | `(required)` |  |
| `input` | `Dict` | `<factory dict>` |  |
| `expected_output` | `Dict` | `<factory dict>` |  |
| `setup_command` | `str` | `''` |  |
| `verify_command` | `str` | `''` |  |
| `description` | `str` | `''` |  |

### Contract
- Path: `tasks[].provides[] / tasks[].consumes[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | `(required)` |  |
| `kind` | `str` | `'artifact'` |  |
| `from_task (alias: `from`)` | `Optional` | `None` |  |
| `schema_hint` | `Union` | `''` |  |
| `signatures` | `Optional` | `None` | Function signatures {fn_name: "(args) -> ret"} |

### SemanticBlock
- Path: `tasks[].semantic`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | `str` | `'advisory'` |  |
| `targets` | `List` | `<factory list>` |  |

### SemanticTarget
- Path: `tasks[].semantic.targets[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `path` | `str` | `(required)` |  |
| `symbol` | `str` | `(required)` |  |
| `op` | `str` | `'modify_body'` |  |
| `inferred` | `bool` | `False` |  |

### AegisDiscipline
- Path: `tasks[].aegis`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `intent` | `Optional` | `None` |  |
| `repair_track` | `Optional` | `None` |  |
| `retirement_track` | `Optional` | `None` |  |
| `baseline_refs` | `Optional` | `None` |  |
| `compat_boundary` | `Optional` | `None` |  |
| `patch_shape_triage` | `Union` | `None` |  |
| `decision_review` | `Union` | `None` |  |
| `drift_check` | `Union` | `None` |  |

### RepairTrack
- Path: `tasks[].aegis.repair_track`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `root_cause` | `Optional` | `None` |  |
| `canonical_owner` | `Optional` | `None` |  |
| `minimal_change` | `Optional` | `None` |  |
| `verification_method` | `Optional` | `None` |  |

### RetirementTrack
- Path: `tasks[].aegis.retirement_track`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `old_owner` | `Optional` | `None` |  |
| `deletion_trigger` | `Optional` | `None` |  |
| `retained` | `Optional` | `None` |  |
| `retention_reason` | `Optional` | `None` |  |

### ModuleSpec
- Path: `tasks[].modules[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `str` | `(required)` |  |
| `description` | `str` | `''` |  |
| `input_spec` | `Dict` | `<factory dict>` |  |
| `output_spec` | `Dict` | `<factory dict>` |  |
| `purpose` | `str` | `''` |  |
| `interface` | `Dict` | `<factory dict>` |  |
| `mock_inputs` | `List` | `<factory list>` |  |
| `expected_outputs` | `List` | `<factory list>` |  |
| `black_box_tests` | `List` | `<factory list>` |  |
| `integration_contract` | `Dict` | `<factory dict>` |  |
| `completion_evidence` | `Dict` | `<factory dict>` |  |
| `internal_depends_on` | `List` | `<factory list>` |  |

### PlanState
- Path: `state`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `completed_task_ids` | `List` | `<factory list>` |  |
| `running_tasks` | `List` | `<factory list>` |  |
| `failed_task_ids` | `List` | `<factory list>` |  |

### RunningTask
- Path: `state.running_tasks[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `task_id` | `str` | `(required)` |  |
| `claimed_paths` | `List` | `<factory list>` |  |

### CriticalFlow
- Path: `critical_flows[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `str` | `(required)` |  |
| `description` | `str` | `''` |  |
| `surface_type` | `Optional` | `None` |  |
| `temporal_pattern` | `Optional` | `None` |  |
| `entrypoints` | `List` | `<factory list>` |  |
| `test_created_by` | `List` | `<factory list>` |  |
| `required_verification_level` | `Literal` | `'integration'` |  |

### ForbiddenFlow
- Path: `forbidden_flows[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `str` | `(required)` |  |
| `description` | `str` | `''` |  |
| `test_created_by` | `List` | `<factory list>` |  |
| `required_verification_level` | `Literal` | `'e2e'` |  |

### FindingRef
- Path: `finding_refs[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `id` | `str` | `''` |  |
| `mitigation` | `str` | `''` |  |
| `enforced_by` | `List` | `<factory list>` |  |
| `status` | `str` | `''` |  |
| `status_reason` | `str` | `''` |  |

### RegistrationInvariant
- Path: `registration_invariants[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | `(required)` |  |
| `description` | `str` | `''` |  |
| `registry_file` | `str` | `(required)` |  |
| `registry_symbol` | `str` | `''` |  |

### SuppressInstance
- Path: `suppress_instances[]`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `code` | `str` | `(required)` |  |
| `owner` | `str` | `''` |  |
| `expiry` | `Optional` | `None` |  |
| `review_after` | `Optional` | `None` |  |
## Non-Suppressible Codes

When a plan contains a security-sensitive `critical_flow` such as auth or RBAC, these codes remain warnings even if they appear in `suppress_codes` or `suppress_instances`.

| Code | Scope |
| --- | --- |
| `W_AGENT_REVIEW_SKIPPED` | Security-sensitive critical flow |
| `W_REVIEWER_SIGNOFF_MISSING` | Security-sensitive critical flow |
| `W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION` | Security-sensitive critical flow |
| `W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW` | Security-sensitive critical flow |
| `W_AUTH_PRIVILEGED_ROLE_FIELD` | Security-sensitive critical flow |
| `W_RBAC_WRITE_ENDPOINT_UNCOVERED` | Security-sensitive critical flow |
| `W_RBAC_FLOW_AUTH_UNVERIFIED` | Security-sensitive critical flow |

## Validation Rules Reference

| Code | Description | Source |
| --- | --- | --- |
| `E_AEGIS_PLACEHOLDER_CONTENT` | Source token reference.<br>f"task '{task.id}' contains placeholder content in {field_name}" | `src/cccc/ralph/validation_rules/discipline.py:51`<br>`src/cccc/ralph/validation_rules/discipline.py:53` |
| `E_AEGIS_RETIREMENT_TRACK_MISSING` | Source token reference.<br>f"{intent} task '{task.id}' has patch-shape risk without retirement_track" | `src/cccc/ralph/validation_rules/discipline.py:72`<br>`src/cccc/ralph/validation_rules/discipline.py:74` |
| `E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW` | Source token reference.<br>f"task '{task.id}' modifies ripple-prone paths but verification only covers itself" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:108`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:110` |
| `E_AEGIS_SECURITY_CHAIN_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:11` |
| `E_AGENT_PROMPT_DIRECT_MODIFICATION` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_agent_prompt.py:13` |
| `E_AGENT_REVIEW_FAILED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_CONSUMER_FROM_NOT_PROVIDER` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' which does not provide it" | `src/cccc/ralph/validation_rules/contracts.py:229`<br>`src/cccc/ralph/validation_rules/contracts.py:230` |
| `E_CONSUMER_FROM_UNKNOWN` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'" | `src/cccc/ralph/validation_rules/contracts.py:56`<br>`src/cccc/ralph/validation_rules/contracts.py:57` |
| `E_CONSUMER_WITHOUT_PROVIDER` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' but no task provides it" | `src/cccc/ralph/validation_rules/contracts.py:46`<br>`src/cccc/ralph/validation_rules/contracts.py:47` |
| `E_CONSUME_PROVIDER_UNRESOLVED` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' without a uniquely resolvable provider" | `src/cccc/ralph/validation_rules/contracts.py:165`<br>`src/cccc/ralph/validation_rules/contracts.py:166` |
| `E_CONTRACT_KIND_MISMATCH` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' as kind '{contract.kind}' but providers declare kind '{provider_kind}'" | `src/cccc/ralph/validation_rules/contracts.py:270`<br>`src/cccc/ralph/validation_rules/contracts.py:271` |
| `E_COVERS_UNKNOWN_FLOW` | Source token reference.<br>f"task '{task.id}' covers flow '{flow_id}' which is not declared in critical_flows or forbidden_flows" | `src/cccc/ralph/validation_rules/coverage.py:2919`<br>`src/cccc/ralph/validation_rules/coverage.py:2920` |
| `E_COVERS_UNKNOWN_TASK` | Source token reference.<br>f"task '{task.id}' covers unknown task '{covered_id}'" | `src/cccc/ralph/validation_rules/structural.py:199`<br>`src/cccc/ralph/validation_rules/structural.py:200` |
| `E_COVERS_WITHOUT_DEP_ORDER` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but '{covered_id}' is not in its transitive dependency closure" | `src/cccc/ralph/validation_rules/structural.py:211`<br>`src/cccc/ralph/validation_rules/structural.py:212` |
| `E_CRITICAL_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:1504`<br>`src/cccc/ralph/validation_rules/coverage.py:1505` |
| `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:1603`<br>`src/cccc/ralph/validation_rules/coverage.py:1604` |
| `E_CRITICAL_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"critical flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:1776`<br>`src/cccc/ralph/validation_rules/coverage.py:1777` |
| `E_CRITICAL_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] critical flow '{flow.id}' is not covered by any task's verification"<br>f"[suppress_flows] critical flow '{flow.id}' is not covered by any task's verification"<br>f"critical flow '{flow.id}' is not covered by any task's verification" | `src/cccc/ralph/validation_rules/coverage.py:1542`<br>`src/cccc/ralph/validation_rules/coverage.py:1543`<br>`src/cccc/ralph/validation_rules/coverage.py:1555`<br>`src/cccc/ralph/validation_rules/coverage.py:1556`<br>`src/cccc/ralph/validation_rules/coverage.py:1577`<br>`src/cccc/ralph/validation_rules/coverage.py:1578`<br>`src/cccc/ralph/validation_rules/coverage.py:1771`<br>`src/cccc/ralph/validation_rules/coverage.py:3268` |
| `E_CYCLE_DETECTED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_DEP_CYCLE` | Source token reference.<br>f"dependency cycle detected involving: {', '.join(cycle)}" | `src/cccc/ralph/validation_rules/structural.py:147`<br>`src/cccc/ralph/validation_rules/structural.py:148` |
| `E_DEP_SELF` | Source token reference.<br>f"task '{t.id}' depends on itself" | `src/cccc/ralph/validation_rules/structural.py:137`<br>`src/cccc/ralph/validation_rules/structural.py:138` |
| `E_DEP_UNKNOWN` | Source token reference.<br>f"task '{t.id}' depends on unknown task '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:126`<br>`src/cccc/ralph/validation_rules/structural.py:127` |
| `E_DUPLICATE_FLOW_ID` | Source token reference.<br>f"duplicate critical_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:3114`<br>`src/cccc/ralph/validation_rules/coverage.py:3115` |
| `E_DUPLICATE_FORBIDDEN_FLOW_ID` | Source token reference.<br>f"duplicate forbidden_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:3128`<br>`src/cccc/ralph/validation_rules/coverage.py:3129` |
| `E_DUPLICATE_INVARIANT_NAME` | Source token reference.<br>f"duplicate registration_invariant name '{inv.name}'" | `src/cccc/ralph/validation_rules/coverage.py:3142`<br>`src/cccc/ralph/validation_rules/coverage.py:3143` |
| `E_DUPLICATE_TASK_ID` | Source token reference.<br>f"duplicate task id '{t.id}'" | `src/cccc/ralph/validation_rules/structural.py:114`<br>`src/cccc/ralph/validation_rules/structural.py:115` |
| `E_FLOW_ID_CROSS_NAMESPACE_COLLISION` | Source token reference.<br>f"flow id '{flow_id}' is declared in both critical_flows and forbidden_flows" | `src/cccc/ralph/validation_rules/coverage.py:3182`<br>`src/cccc/ralph/validation_rules/coverage.py:3183` |
| `E_FLOW_TEST_CREATED_BY_UNKNOWN_TASK` | Source token reference.<br>f"{namespace} flow '{flow.id}' references unknown test_created_by task '{task_id}'" | `src/cccc/ralph/validation_rules/coverage.py:3167`<br>`src/cccc/ralph/validation_rules/coverage.py:3168` |
| `E_FLOW_TEST_CREATOR_FAILED` | Source token reference.<br>f"critical flow '{flow.id}' is uncovered because its test creator task already failed"<br>f"forbidden flow '{flow.id}' is uncovered because its test creator task already failed" | `src/cccc/ralph/validation_rules/coverage.py:1527`<br>`src/cccc/ralph/validation_rules/coverage.py:1528`<br>`src/cccc/ralph/validation_rules/coverage.py:2433`<br>`src/cccc/ralph/validation_rules/coverage.py:2434` |
| `E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"forbidden flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:2486`<br>`src/cccc/ralph/validation_rules/coverage.py:2487` |
| `E_FORBIDDEN_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] forbidden flow '{flow.id}' has no negative test covering it"<br>f"forbidden flow '{flow.id}' has no negative test covering it" | `src/cccc/ralph/validation_rules/coverage.py:2453`<br>`src/cccc/ralph/validation_rules/coverage.py:2454`<br>`src/cccc/ralph/validation_rules/coverage.py:2475`<br>`src/cccc/ralph/validation_rules/coverage.py:2476` |
| `E_MISSING_CLAIMED_PATHS` | Source token reference.<br>f"task '{t.id}' has no claimed_paths" | `src/cccc/ralph/validation_rules/structural.py:231`<br>`src/cccc/ralph/validation_rules/structural.py:232` |
| `E_MISSING_INTEGRATION_SPINE` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no task provides integration/e2e verification covering multiple tasks' | `src/cccc/ralph/validation_rules/structural.py:808`<br>`src/cccc/ralph/validation_rules/structural.py:809` |
| `E_MISSING_VERIFICATION` | Source token reference.<br>f"task '{t.id}' has no verification defined" | `src/cccc/ralph/validation_rules/structural.py:239`<br>`src/cccc/ralph/validation_rules/structural.py:240` |
| `E_MOCK_TEST_MISSING_NAME` | Source token reference.<br>f"task '{t.id}' has a mock_test with empty name" | `src/cccc/ralph/validation_rules/coverage.py:2383`<br>`src/cccc/ralph/validation_rules/coverage.py:2384` |
| `E_MOCK_TEST_MISSING_VERIFY_COMMAND` | Source token reference.<br>f"task '{t.id}' mock_test '{mt.name}' has no verify_command" | `src/cccc/ralph/validation_rules/coverage.py:2390`<br>`src/cccc/ralph/validation_rules/coverage.py:2391` |
| `E_MODULE_DEP_CYCLE` | Source token reference.<br>f"task '{task.id}' has a module dependency cycle"<br>f"task '{task_id}' module '{module.id}' depends on itself" | `src/cccc/ralph/validation_rules/structural.py:1050`<br>`src/cccc/ralph/validation_rules/structural.py:1051`<br>`src/cccc/ralph/validation_rules/structural.py:1217`<br>`src/cccc/ralph/validation_rules/structural.py:1218` |
| `E_MODULE_DUPLICATE_ID` | Source token reference.<br>f"task '{task.id}' has duplicate module id '{mod.id}'" | `src/cccc/ralph/validation_rules/structural.py:1010`<br>`src/cccc/ralph/validation_rules/structural.py:1018`<br>`src/cccc/ralph/validation_rules/structural.py:1019` |
| `E_MODULE_UNKNOWN_DEP` | Source token reference.<br>f"task '{task.id}' module '{mod.id}' depends on unknown module '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:1010`<br>`src/cccc/ralph/validation_rules/structural.py:1029`<br>`src/cccc/ralph/validation_rules/structural.py:1030` |
| `E_NO_CROSS_TASK_VERIFICATION` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no integration/e2e verification covers multiple tasks' | `src/cccc/ralph/validation_rules/coverage.py:177`<br>`src/cccc/ralph/validation_rules/coverage.py:178` |
| `E_SECURITY_CRITICAL_FLOW_SUPPRESSED` | Source token reference.<br>f"security-sensitive critical flow '{flow_id}' cannot be suppressed with suppress_flows" | `src/cccc/ralph/validation_rules/security.py:203`<br>`src/cccc/ralph/validation_rules/security.py:204`<br>`src/cccc/ralph/validation_rules/security.py:72` |
| `E_STATE_RUNNING_TASK_INVALID_CLAIMS` | Source token reference.<br>f"running task '{task_id}' has invalid claimed_paths ({reason})" | `src/cccc/ralph/validation_rules/coverage.py:3466`<br>`src/cccc/ralph/validation_rules/coverage.py:3467` |
| `E_STATE_TASK_STATUS_CONFLICT` | Source token reference.<br>f"state bucket '{bucket_name}' contains duplicate task id '{task_id}'"<br>f"task '{task_id}' appears in both state buckets '{left_bucket}' and '{right_bucket}'" | `src/cccc/ralph/validation_rules/coverage.py:2981`<br>`src/cccc/ralph/validation_rules/coverage.py:2982`<br>`src/cccc/ralph/validation_rules/coverage.py:2991`<br>`src/cccc/ralph/validation_rules/coverage.py:2992` |
| `E_TASK_PATH_OUTSIDE_PLAN_SCOPE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:37` |
| `E_UNCOVERED_REQUIRED_ISSUE` | Source token reference.<br>f"required issue '{issue_id}' is not addressed by any task" | `src/cccc/ralph/validation_rules/coverage.py:2051`<br>`src/cccc/ralph/validation_rules/coverage.py:2052`<br>`src/cccc/ralph/validation_rules/coverage.py:3271` |
| `E_VERIFICATION_NON_GATING` | Source token reference.<br>f"task '{task.id}' verification cannot gate completion at runtime" | `src/cccc/ralph/validation_rules/coverage.py:231`<br>`src/cccc/ralph/validation_rules/coverage.py:232` |
| `E_VERIFICATION_SHALLOW_CRITICAL` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:264` |
| `E_VERIFICATION_TARGET_MISSING_FILE` | Source token reference.<br>f"task '{task_id}' references missing file '{rel_path}'" | `src/cccc/ralph/filesystem_validator.py:1124`<br>`src/cccc/ralph/filesystem_validator.py:1125` |
| `E_WRITE_CONFLICT` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:34` |
| `H_DUPLICATE_ISSUE_ADDRESS` | Source token reference.<br>f"issue '{issue_id}' is addressed by multiple tasks: {', '.join(sorted(task_ids))}" | `src/cccc/ralph/validation_rules/coverage.py:2351`<br>`src/cccc/ralph/validation_rules/coverage.py:2352` |
| `H_MOCK_TESTS_ON_RALPH_MODE` | Source token reference.<br>f"task '{t.id}' has mock_tests but verification_mode='ralph'; mock_tests only run in agent/challenge mode" | `src/cccc/ralph/validation_rules/coverage.py:2372`<br>`src/cccc/ralph/validation_rules/coverage.py:2373` |
| `H_SUPPRESS_UNUSED` | Source token reference.<br>f"suppress_codes entry '{code}' did not match any emitted issue" | `src/cccc/ralph/validation_rules/coverage.py:3248`<br>`src/cccc/ralph/validation_rules/coverage.py:3249` |
| `H_VERIFICATION_COMMAND_DEAD` | Source token reference.<br>f"task '{task.id}' verification.command is ignored in favor of structured checks" | `src/cccc/ralph/validation_rules/coverage.py:1181`<br>`src/cccc/ralph/validation_rules/coverage.py:1182` |
| `W_ACCEPTANCE_COVERAGE_GAP` | Source token reference.<br>f"issue '{issue_id}' acceptance coverage is {coverage:.2f} ({len(matched_keywords)}/{len(tracker_keywords)} tracker keywords matched)" | `src/cccc/ralph/validation_rules/coverage.py:2106`<br>`src/cccc/ralph/validation_rules/coverage.py:2107` |
| `W_AEGIS_COMPLEX_MISSING_BASELINE` | Source token reference.<br>f"complex task '{task.id}' has no aegis.baseline_refs" | `src/cccc/ralph/validation_rules/discipline.py:128`<br>`src/cccc/ralph/validation_rules/discipline.py:130` |
| `W_AEGIS_DECISION_HYGIENE_MISSING` | Source token reference.<br>f"task '{task.id}' introduces owner-pattern risk without decision_review" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:58`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:60` |
| `W_AEGIS_DRIFT_CHECK_MISSING` | Source token reference.<br>f"task '{task.id}' has {module_count} modules without aegis.drift_check" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:77`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:79` |
| `W_AEGIS_FIX_NO_REPAIR_TRACK` | Source token reference.<br>f"fix task '{task.id}' has no repair_track" | `src/cccc/ralph/validation_rules/discipline.py:90`<br>`src/cccc/ralph/validation_rules/discipline.py:92` |
| `W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has patch-shape risk without aegis.patch_shape_triage" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:23`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:25` |
| `W_AEGIS_PLAN_NO_COMPAT_BOUNDARY` | Source token reference.<br>plan has cross-task dependencies but no task declares aegis.compat_boundary | `src/cccc/ralph/validation_rules/discipline_second_wave.py:92`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:93` |
| `W_AEGIS_RIPPLE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has ripple risk without downstream awareness_paths" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:41`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:43` |
| `W_AEGIS_TDD_NO_TEST_PATH` | Source token reference.<br>f"{intent} task '{task.id}' claims no test path" | `src/cccc/ralph/validation_rules/discipline.py:109`<br>`src/cccc/ralph/validation_rules/discipline.py:111` |
| `W_AF_ASSIGNMENT_BYPASS_ACQUIRE` | Source token reference.<br>f'task {task.id!r} describes explicit assignment without mentioning acquire() protocol' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:137`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:142`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:143` |
| `W_AF_ENGINE_PREFERENCE_UNSUBSTANTIATED` | Source token reference.<br>plan declares execution_engine='af' without any agentflow/ path in plan_scope | `src/cccc/ralph/validation_rules/agentflow_invariants.py:53`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:54` |
| `W_AF_LEASE_RELEASE_INCOMPLETE` | Source token reference.<br>f'task {task.id!r} handles lease operations but does not cover all terminal paths: missing {sorted(missing)}' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:219`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:236`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:237` |
| `W_AF_PATCH_COVERAGE_INCOMPLETE` | Source token reference.<br>f'task {task.id!r} modifies AF patches without test coverage' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:87`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:94`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:95` |
| `W_AF_PROMPT_BYPASS_PROMOTION` | Source token reference.<br>f'task {task.id!r} modifies AF prompt paths without promotion flow reference' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:156`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:170`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:171` |
| `W_AF_SILENT_LEGACY_FALLBACK` | Source token reference.<br>f'task {task.id!r} touches both AF and legacy engine paths without declaring engine preference or fallback strategy' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:48`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:73`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:74` |
| `W_AF_TRACE_PARSER_SILENT_FAILURE` | Source token reference.<br>f'task {task.id!r} modifies trace parser without error event handling declaration' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:192`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:205`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:206` |
| `W_AF_VERIFICATION_GATE_AUTHORITY` | Source token reference.<br>f'task {task.id!r} modifies AF state files without referencing VerificationGate' | `src/cccc/ralph/validation_rules/agentflow_invariants.py:105`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:117`<br>`src/cccc/ralph/validation_rules/agentflow_invariants.py:118` |
| `W_AF_VERIFICATION_GATE_BYPASS` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:3096`<br>`src/cccc/ralph/validation_rules/coverage.py:3097` |
| `W_AGENT_REVIEW_SKIPPED` | Source token reference. | `src/cccc/ralph/validation_rules/security.py:73` |
| `W_AUTH_PRIVILEGED_ROLE_FIELD` | Source token reference.<br>f"identity surface flow '{flow.id}' lacks a privileged-role-field boundary test" | `src/cccc/ralph/validation_rules/security.py:145`<br>`src/cccc/ralph/validation_rules/security.py:146`<br>`src/cccc/ralph/validation_rules/security.py:78` |
| `W_AUTH_TIMING_UNSAFE` | Source token reference. | `src/cccc/ralph/security_recipes.py:49` |
| `W_AUTH_TYPE_CAST_UNGUARDED` | Source token reference.<br>f"auth flow '{getattr(flow, 'id', '')}' lacks malformed-input rejection coverage for auth boundary type safety" | `src/cccc/ralph/validation_rules/security.py:79`<br>`src/cccc/ralph/validation_rules/security_auth_boundary.py:62`<br>`src/cccc/ralph/validation_rules/security_auth_boundary.py:63` |
| `W_BATCH_E2E_NO_COMMAND` | Source token reference.<br>f"plan has {dep_layers} dependency layers but no batch_e2e_command — cross-task integration won't be verified between batches" | `src/cccc/ralph/validation_rules/coverage.py:3557`<br>`src/cccc/ralph/validation_rules/coverage.py:3567`<br>`src/cccc/ralph/validation_rules/coverage.py:3568` |
| `W_CLAIMED_PATH_INCOMPLETE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:36` |
| `W_CLAIMED_TEST_NOT_EXERCISED` | Source token reference.<br>f"task '{task.id}' claims test file '{test_path}' but no verification check exercises it" | `src/cccc/ralph/validation_rules/coverage.py:1948`<br>`src/cccc/ralph/validation_rules/coverage.py:1949` |
| `W_CONFTEST_COVERAGE_GAP` | Source token reference.<br>f"task '{task_id}' source '{source_path}' has {count} related conftest(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:386`<br>`src/cccc/ralph/filesystem_validator.py:387`<br>`src/cccc/ralph/filesystem_validator.py:593` |
| `W_CONSUME_WITHOUT_DEP` | Source token reference.<br>f"task '{t.id}' consumes from '{src}' but does not depend on it" | `src/cccc/ralph/validation_rules/contracts.py:194`<br>`src/cccc/ralph/validation_rules/contracts.py:195` |
| `W_CONTRACT_SCHEMA_MISMATCH` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' with an incompatible schema hint" | `src/cccc/ralph/validation_rules/contracts.py:67`<br>`src/cccc/ralph/validation_rules/contracts.py:68` |
| `W_CONTRACT_SIGNATURE_MISMATCH` | Source token reference.<br>f"task '{consumer_task_id}' consumes '{consumer.name}' with signature mismatch" | `src/cccc/ralph/validation_rules/contracts.py:350`<br>`src/cccc/ralph/validation_rules/contracts.py:351` |
| `W_COVERS_CLAIM_UNVERIFIABLE` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification command does not reference any claimed_paths of '{covered_id}'" | `src/cccc/ralph/validation_rules/coverage.py:1426`<br>`src/cccc/ralph/validation_rules/coverage.py:1427` |
| `W_COVERS_NOT_EXERCISED` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification does not reference the covered paths" | `src/cccc/ralph/validation_rules/coverage.py:1205`<br>`src/cccc/ralph/validation_rules/coverage.py:1206` |
| `W_CRITICAL_DECLARATION_OUTSIDE_PLAN_SCOPE` | Source token reference.<br>critical_entrypoints are declared entirely outside plan_scope<br>f"critical flow '{flow.id}' is declared entirely outside plan_scope" | `src/cccc/ralph/validation_rules/coverage.py:3216`<br>`src/cccc/ralph/validation_rules/coverage.py:3217`<br>`src/cccc/ralph/validation_rules/coverage.py:3230`<br>`src/cccc/ralph/validation_rules/coverage.py:3231` |
| `W_CRITICAL_FLOW_NO_ENTRYPOINTS` | Source token reference.<br>f"critical flow '{flow.id}' has no entrypoints declared" | `src/cccc/ralph/validation_rules/coverage.py:3196`<br>`src/cccc/ralph/validation_rules/coverage.py:3197` |
| `W_CRITICAL_FLOW_NO_INDEPENDENT_REVIEW` | Source token reference.<br>f"critical flow '{flow.id}' has coverage but no independent review semantics" | `src/cccc/ralph/validation_rules/coverage.py:1822`<br>`src/cccc/ralph/validation_rules/coverage.py:1823`<br>`src/cccc/ralph/validation_rules/security.py:76` |
| `W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims critical flow entrypoints but uses verification_mode='{task.verification_mode}' instead of agent/challenge" | `src/cccc/ralph/validation_rules/coverage.py:1799`<br>`src/cccc/ralph/validation_rules/coverage.py:1800`<br>`src/cccc/ralph/validation_rules/security.py:75` |
| `W_CROSS_BOUNDARY_WITHOUT_GLUE` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' across different path boundaries, but no integration/e2e verification covers both" | `src/cccc/ralph/validation_rules/structural.py:786`<br>`src/cccc/ralph/validation_rules/structural.py:787` |
| `W_CROSS_TASK_IO_MISMATCH` | Source token reference.<br>f"task '{task.id}' expects input keys {sorted(missing)} not provided by any upstream dependency's expected_output" | `src/cccc/ralph/validation_rules/contracts.py:469`<br>`src/cccc/ralph/validation_rules/contracts.py:491`<br>`src/cccc/ralph/validation_rules/contracts.py:492` |
| `W_DEP_WITHOUT_CONSUME` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' which provides contracts, but does not consume any of them" | `src/cccc/ralph/validation_rules/contracts.py:206`<br>`src/cccc/ralph/validation_rules/contracts.py:207` |
| `W_DISCIPLINE_RULE_UNREGISTERED` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_registration.py:15`<br>`src/cccc/ralph/validation_rules/discipline_registration.py:41` |
| `W_DISCONNECTED_COMPONENTS` | Source token reference.<br>f'plan has {len(components)} disconnected task groups' | `src/cccc/ralph/validation_rules/structural.py:158`<br>`src/cccc/ralph/validation_rules/structural.py:159` |
| `W_DOC_PARITY_SCOPE` | Source token reference. | `src/cccc/ralph/validation_rules/doc_parity.py:88` |
| `W_DOC_WRITER_CHECKER_SECTION_DRIFT` | Source token reference. | `src/cccc/ralph/validation_rules/doc_parity.py:15`<br>`src/cccc/ralph/validation_rules/doc_parity.py:157` |
| `W_DYNAMIC_TEST_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' source '{source_path}' is dynamically imported by '{test_path}'" | `src/cccc/ralph/filesystem_validator.py:370`<br>`src/cccc/ralph/filesystem_validator.py:584`<br>`src/cccc/ralph/filesystem_validator.py:585` |
| `W_E2E_MISSING_COMPILE_CHECK` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:41` |
| `W_EMPTY_ACCEPTANCE` | Source token reference.<br>f"task '{t.id}' has no acceptance_criteria" | `src/cccc/ralph/validation_rules/structural.py:247`<br>`src/cccc/ralph/validation_rules/structural.py:248` |
| `W_EVALUATION_PLACEHOLDER_REMAINING` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:42` |
| `W_FINDING_REF_INCOMPLETE` | Source token reference.<br>f"finding_ref '{ref.id}' is missing mitigation"<br>finding_ref is missing id | `src/cccc/ralph/validation_rules/coverage.py:2847`<br>`src/cccc/ralph/validation_rules/coverage.py:2848`<br>`src/cccc/ralph/validation_rules/coverage.py:2854`<br>`src/cccc/ralph/validation_rules/coverage.py:2855` |
| `W_FINDING_REF_UNKNOWN_ENFORCER` | Source token reference.<br>f"finding_ref '{ref.id}' references unknown enforcer '{enforcer}'" | `src/cccc/ralph/validation_rules/coverage.py:2863`<br>`src/cccc/ralph/validation_rules/coverage.py:2864` |
| `W_FLOW_COVERAGE_DEFERRED` | Source token reference.<br>[deferred] flow coverage not yet satisfied (creator pending) | `src/cccc/ralph/validation_rules/coverage.py:1565`<br>`src/cccc/ralph/validation_rules/coverage.py:1566`<br>`src/cccc/ralph/validation_rules/coverage.py:2463`<br>`src/cccc/ralph/validation_rules/coverage.py:2464` |
| `W_FLOW_OWNER_NO_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims entrypoint '{entrypoint}' of flow '{flow.id}' but doesn't verify the flow" | `src/cccc/ralph/validation_rules/coverage.py:1739`<br>`src/cccc/ralph/validation_rules/coverage.py:1740` |
| `W_FLOW_SEGMENT_UNOWNED` | Source token reference.<br>f"task '{task.id}' covers flow '{flow.id}' but doesn't claim any of its entrypoints" | `src/cccc/ralph/validation_rules/coverage.py:1722`<br>`src/cccc/ralph/validation_rules/coverage.py:1723` |
| `W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:125`<br>`src/cccc/ralph/validation_rules/coverage.py:2581` |
| `W_FORBIDDEN_FLOW_FIELD_TEST_UNVERIFIABLE` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:126`<br>`src/cccc/ralph/validation_rules/coverage.py:2657` |
| `W_FORBIDDEN_FLOW_FIELD_UNCOVERED` | Source token reference.<br>f'forbidden flow {flow_id!r} declares fields {sorted(uncovered_fields)} but no covering task verifies them' | `src/cccc/ralph/validation_rules/coverage.py:2600`<br>`src/cccc/ralph/validation_rules/coverage.py:2601` |
| `W_FORBIDDEN_FLOW_FIELD_UNTESTED` | Source token reference.<br>but covering verification checks do not mention them in test files | `src/cccc/ralph/validation_rules/coverage.py:2569`<br>`src/cccc/ralph/validation_rules/coverage.py:2570` |
| `W_FTS_CJK_SUBSTRING_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:13` |
| `W_FULL_REGRESSION_OVERRIDE_RISK` | Source token reference.<br>f"task '{task.id}' runs a full pytest gate while override signals exist elsewhere in the plan" | `src/cccc/ralph/validation_rules/coverage.py:3310`<br>`src/cccc/ralph/validation_rules/coverage.py:3311` |
| `W_GLOBAL_WRITE_CLAIM` | Source token reference.<br>f"task '{t.id}' claims global write ('/') — blocks all parallel tasks" | `src/cccc/ralph/validation_rules/structural.py:268`<br>`src/cccc/ralph/validation_rules/structural.py:269` |
| `W_GOAL_CJK_TOKENIZATION_HINT` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:40` |
| `W_GOAL_REFERENCES_UNCLAIMED_PATH` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:38` |
| `W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:39` |
| `W_GUARD_AFTER_SIDE_EFFECT` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:130`<br>`src/cccc/ralph/validation_rules/coverage.py:683` |
| `W_INDIRECT_TEST_IMPORT` | Source token reference.<br>f"task '{task_id}' has {len(entries)} indirect test import hint(s) not covered by any verification; showing first {len(samples)} sample(s)"<br>f"task '{task_id}' source '{source_path}' has {count} related test(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:629`<br>`src/cccc/ralph/filesystem_validator.py:630`<br>`src/cccc/ralph/filesystem_validator.py:646`<br>`src/cccc/ralph/filesystem_validator.py:647` |
| `W_INTEGRATION_CLAIM_EVIDENCE_MISSING` | Source token reference.<br>f"task '{task_id}' integration claim lacks supporting evidence" | `src/cccc/ralph/validation_rules/coverage.py:806`<br>`src/cccc/ralph/validation_rules/coverage.py:807` |
| `W_INTEGRATION_DORMANT_PATH` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:128`<br>`src/cccc/ralph/validation_rules/coverage.py:599` |
| `W_INTEGRATION_IMPORT_ONLY_NO_CALL` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:127`<br>`src/cccc/ralph/validation_rules/coverage.py:484` |
| `W_INTEGRATION_INTERFACE_MISMATCH` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' but verification does not reference any of {contract.from_task}'s paths" | `src/cccc/ralph/validation_rules/contracts.py:125`<br>`src/cccc/ralph/validation_rules/contracts.py:126` |
| `W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE` | Source token reference.<br>f"task '{task.id}' integration claim lacks production call evidence" | `src/cccc/ralph/validation_rules/coverage.py:504`<br>`src/cccc/ralph/validation_rules/coverage.py:505`<br>`src/cccc/ralph/validation_rules/security.py:70` |
| `W_INTEGRATION_ROLE_WEAK_VERIFICATION` | Source token reference.<br>f"task '{task.id}' has role='integration' but lacks integration/e2e verification covering at least 2 tasks" | `src/cccc/ralph/validation_rules/structural.py:841`<br>`src/cccc/ralph/validation_rules/structural.py:842` |
| `W_INTEGRATION_TASK_SHALLOW_VERIFICATION` | Source token reference.<br>f"task '{task.id}' integration verification is shallow and lacks a behavioral check" | `src/cccc/ralph/validation_rules/coverage.py:399`<br>`src/cccc/ralph/validation_rules/coverage.py:400`<br>`src/cccc/ralph/validation_rules/security.py:70` |
| `W_ISOLATED_TASK` | Source token reference.<br>f"task '{t.id}' has no dependency edges (neither depends on others nor depended upon)" | `src/cccc/ralph/validation_rules/structural.py:174`<br>`src/cccc/ralph/validation_rules/structural.py:175` |
| `W_LEAF_ROLE_IS_INTEGRATOR` | Source token reference.<br>f"task '{task.id}' has role='leaf' but provides integration/e2e verification covering multiple tasks" | `src/cccc/ralph/validation_rules/structural.py:881`<br>`src/cccc/ralph/validation_rules/structural.py:882` |
| `W_MODULE_INTEGRATION_CONTRACT_UNRESOLVED` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:1160`<br>`src/cccc/ralph/validation_rules/structural.py:45` |
| `W_MODULE_NO_BLACKBOX_EVIDENCE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:1142`<br>`src/cccc/ralph/validation_rules/structural.py:44` |
| `W_MODULE_STRUCTURE_INCOMPLETE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:1129`<br>`src/cccc/ralph/validation_rules/structural.py:43` |
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | Source token reference.<br>all cross-task integration/e2e verifiers are sink tasks and appear late in the graph | `src/cccc/ralph/validation_rules/structural.py:921`<br>`src/cccc/ralph/validation_rules/structural.py:922` |
| `W_NO_FAILURE_PATH` | Source token reference.<br>f"task '{t.id}' involves assignment/actor operations but has no failure handling description or failure_path field" | `src/cccc/ralph/validation_rules/coverage.py:1264`<br>`src/cccc/ralph/validation_rules/coverage.py:1265` |
| `W_PLAN_SCOPE_UNUSED` | Source token reference.<br>f"registration invariant '{inv.name}' references '{inv.registry_file}' which is not claimed by any task" | `src/cccc/ralph/validation_rules/coverage.py:3286`<br>`src/cccc/ralph/validation_rules/coverage.py:3287` |
| `W_PROVIDER_UNUSED` | Source token reference.<br>f"contract '{name}' is provided but never consumed" | `src/cccc/ralph/validation_rules/contracts.py:93`<br>`src/cccc/ralph/validation_rules/contracts.py:94` |
| `W_RBAC_FLOW_AUTH_UNVERIFIED` | Source token reference.<br>f"no authentication-related verification check found for RBAC flow '{flow.id}'" | `src/cccc/ralph/validation_rules/security.py:100`<br>`src/cccc/ralph/validation_rules/security.py:81`<br>`src/cccc/ralph/validation_rules/security.py:99` |
| `W_RBAC_WRITE_ENDPOINT_UNCOVERED` | Source token reference.<br>f"RBAC write flow '{flow.id}' lacks an authorization-negative verification check" | `src/cccc/ralph/validation_rules/security.py:120`<br>`src/cccc/ralph/validation_rules/security.py:121`<br>`src/cccc/ralph/validation_rules/security.py:80` |
| `W_REGISTRATION_INVARIANT_UNCOVERED` | Source token reference.<br>f"registration invariant '{inv.name}' registry file '{inv.registry_file}' is not claimed by any task" | `src/cccc/ralph/filesystem_validator.py:465`<br>`src/cccc/ralph/filesystem_validator.py:466` |
| `W_REVIEWER_SIGNOFF_MISSING` | Source token reference.<br>f"security-sensitive flow '{flow.id}' has review semantics but no auditable sign-off reference" | `src/cccc/ralph/validation_rules/security.py:173`<br>`src/cccc/ralph/validation_rules/security.py:174`<br>`src/cccc/ralph/validation_rules/security.py:74` |
| `W_REVIEW_FINDING_NO_ADOPTION` | Source token reference. | `src/cccc/ralph/validation_rules/discipline.py:152`<br>`src/cccc/ralph/validation_rules/discipline.py:169`<br>`src/cccc/ralph/validation_rules/discipline.py:30` |
| `W_SECURITY_REVIEW_NOT_INDEPENDENT` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:124`<br>`src/cccc/ralph/validation_rules/coverage.py:1854`<br>`src/cccc/ralph/validation_rules/coverage.py:1866`<br>`src/cccc/ralph/validation_rules/security.py:10`<br>`src/cccc/ralph/validation_rules/security.py:77` |
| `W_SEMANTIC_DEFAULT_PARTIAL_UPDATE` | Source token reference. | `src/cccc/ralph/validation_rules/semantic_defaults.py:13`<br>`src/cccc/ralph/validation_rules/semantic_defaults.py:224` |
| `W_SEMANTIC_DEFAULT_VALUE_DRIFT` | Source token reference. | `src/cccc/ralph/validation_rules/semantic_defaults.py:14`<br>`src/cccc/ralph/validation_rules/semantic_defaults.py:179` |
| `W_SHARED_FILE_PARTIAL_VERIFICATION` | Source token reference.<br>f"tasks '{t1.id}' and '{t2.id}' share paths but neither verification mentions them" | `src/cccc/ralph/validation_rules/structural.py:738`<br>`src/cccc/ralph/validation_rules/structural.py:739` |
| `W_SHARED_PATH_NO_DEPENDENCY` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:35` |
| `W_SIGNOFF_STRUCTURE_WEAK` | Source token reference.<br>f"security-sensitive flow '{flow.id}' has an auditable sign-off reference with weak structure in review task '{task.id}'" | `src/cccc/ralph/validation_rules/security.py:82`<br>`src/cccc/ralph/validation_rules/security_signoff.py:197`<br>`src/cccc/ralph/validation_rules/security_signoff.py:198` |
| `W_SILENT_DEGRADATION_UNCHECKED` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:14` |
| `W_SILENT_FALLBACK` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:129`<br>`src/cccc/ralph/validation_rules/coverage.py:641` |
| `W_SSRF_ENCODING_UNCOVERED` | Source token reference. | `src/cccc/ralph/security_recipes.py:39` |
| `W_SSRF_ROUTE_BINDING_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:12` |
| `W_STATE_MACHINE_CONCURRENCY_UNVERIFIED` | Source token reference. | `src/cccc/ralph/validation_rules/security.py:16`<br>`src/cccc/ralph/validation_rules/security.py:69`<br>`src/cccc/ralph/validation_rules/security_state_machine.py:42`<br>`src/cccc/ralph/validation_rules/security_state_machine.py:49`<br>`src/cccc/ralph/validation_rules/security_state_machine.py:9` |
| `W_STATE_UNKNOWN_TASK_REF` | Source token reference.<br>f"state.completed_task_ids references unknown task '{tid}'"<br>f"state.failed_task_ids references unknown task '{tid}'"<br>f"state.running_tasks references unknown task '{rt.task_id}'" | `src/cccc/ralph/validation_rules/coverage.py:2939`<br>`src/cccc/ralph/validation_rules/coverage.py:2940`<br>`src/cccc/ralph/validation_rules/coverage.py:2951`<br>`src/cccc/ralph/validation_rules/coverage.py:2952`<br>`src/cccc/ralph/validation_rules/coverage.py:2963`<br>`src/cccc/ralph/validation_rules/coverage.py:2964` |
| `W_STATUS_CODE_DRIFT` | Source token reference.<br>f'task {task.id!r} goal_behavior declares status codes {sorted(drifted)} not present in acceptance_criteria' | `src/cccc/ralph/validation_rules/coverage.py:2134`<br>`src/cccc/ralph/validation_rules/coverage.py:2135` |
| `W_STATUS_CODE_IMPLEMENTATION_DRIFT` | Source token reference.<br>f'task {task.id!r} goal_behavior declares status codes {sorted(drifted)} not present in claimed Python sources' | `src/cccc/ralph/validation_rules/coverage.py:2210`<br>`src/cccc/ralph/validation_rules/coverage.py:2211` |
| `W_SUPPRESS_FLOWS_UNKNOWN` | Source token reference.<br>f"suppress_flows references unknown flow '{flow_id}'" | `src/cccc/ralph/validation_rules/coverage.py:2879`<br>`src/cccc/ralph/validation_rules/coverage.py:2880` |
| `W_TASK_ADDRESSES_DISJOINT` | Source token reference.<br>f"task '{t.id}' addresses issues from different domains: {', '.join(sorted(prefixes))}" | `src/cccc/ralph/validation_rules/coverage.py:2333`<br>`src/cccc/ralph/validation_rules/coverage.py:2334` |
| `W_TASK_GRANULARITY_COMPRESSION` | Source token reference. | `src/cccc/ralph/validation_rules/task_granularity.py:11`<br>`src/cccc/ralph/validation_rules/task_granularity.py:123` |
| `W_TEST_COVERAGE_GAP` | Source code assignment literal.<br>Source token reference. | `src/cccc/ralph/filesystem_validator.py:395`<br>`src/cccc/ralph/filesystem_validator.py:593` |
| `W_TOKEN_TYPE_CONFUSION_UNCOVERED` | Source token reference. | `src/cccc/ralph/security_recipes.py:67` |
| `W_UNCLAIMED_TEST_FOR_SOURCE` | Source token reference.<br>f"task '{task.id}' source '{source_path}' has related test '{test_path}' claimed by no task" | `src/cccc/ralph/filesystem_validator.py:508`<br>`src/cccc/ralph/filesystem_validator.py:509` |
| `W_UNKNOWN_VERIFICATION_MODE` | Source token reference.<br>f"task '{t.id}' has unknown verification_mode '{t.verification_mode}'" | `src/cccc/ralph/validation_rules/structural.py:257`<br>`src/cccc/ralph/validation_rules/structural.py:258` |
| `W_VERIFICATION_BEHAVIOR_MISMATCH` | Source token reference.<br>f"task '{t.id}' goal implies runtime behavior but verification is only {v.level}-level" | `src/cccc/ralph/validation_rules/coverage.py:1319`<br>`src/cccc/ralph/validation_rules/coverage.py:1320`<br>`src/cccc/ralph/validation_rules/security.py:70` |
| `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` | Source token reference.<br>f"task '{task_id}' verification contains shell operators and was skipped" | `src/cccc/ralph/filesystem_validator.py:750`<br>`src/cccc/ralph/filesystem_validator.py:751` |
| `W_VERIFICATION_CROSS_SCOPE` | Source token reference.<br>f"task '{task.id}' verification check '{check.name}' references path '{ref_path}' which belongs to task '{other_id}'"<br>f"task '{task.id}' verification command references path '{ref_path}' which belongs to task '{other_id}'" | `src/cccc/ralph/validation_rules/coverage.py:1360`<br>`src/cccc/ralph/validation_rules/coverage.py:1361`<br>`src/cccc/ralph/validation_rules/coverage.py:1386`<br>`src/cccc/ralph/validation_rules/coverage.py:1387` |
| `W_VERIFICATION_DUPLICATE_COMMAND` | Source token reference.<br>f'tasks {task_ids} share the same verification command' | `src/cccc/ralph/validation_rules/coverage.py:1292`<br>`src/cccc/ralph/validation_rules/coverage.py:1293` |
| `W_VERIFICATION_IMPORT_MODULE_MISSING` | Source token reference.<br>f"task '{task_id}' imports module '{module_name}' which only the task itself claims (self-verification)"<br>message | `src/cccc/ralph/filesystem_validator.py:1151`<br>`src/cccc/ralph/filesystem_validator.py:1152`<br>`src/cccc/ralph/filesystem_validator.py:1167`<br>`src/cccc/ralph/filesystem_validator.py:1168` |
| `W_VERIFICATION_IMPORT_SYMBOL_MISSING` | Source token reference.<br>f"task '{task_id}' imports missing symbol '{alias.name}' from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:953`<br>`src/cccc/ralph/filesystem_validator.py:954` |
| `W_VERIFICATION_NO_CHECKS` | Source token reference.<br>f"task '{t.id}' has a verification command but no structured checks — consider splitting into at least a compile check and a behavior test check" | `src/cccc/ralph/validation_rules/coverage.py:207`<br>`src/cccc/ralph/validation_rules/coverage.py:208` |
| `W_VERIFICATION_NO_MAIN_PATH_COMMAND` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:131`<br>`src/cccc/ralph/validation_rules/coverage.py:370` |
| `W_VERIFICATION_PYTEST_K_NO_MATCH` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:1065`<br>`src/cccc/ralph/filesystem_validator.py:1066` |
| `W_VERIFICATION_PYTEST_NODE_MISSING` | Source token reference.<br>f"task '{task_id}' pytest target node '{node_part}' was not found in '{file_path}'" | `src/cccc/ralph/filesystem_validator.py:1022`<br>`src/cccc/ralph/filesystem_validator.py:1023` |
| `W_VERIFICATION_PYTHON_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' import target '{module_name}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet is opaque to static import checks"<br>f"task '{task_id}' python -c uses relative or opaque imports"<br>f"task '{task_id}' uses wildcard import from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:880`<br>`src/cccc/ralph/filesystem_validator.py:881`<br>`src/cccc/ralph/filesystem_validator.py:904`<br>`src/cccc/ralph/filesystem_validator.py:905`<br>`src/cccc/ralph/filesystem_validator.py:932`<br>`src/cccc/ralph/filesystem_validator.py:933`<br>`src/cccc/ralph/filesystem_validator.py:943`<br>`src/cccc/ralph/filesystem_validator.py:944` |
| `W_VERIFICATION_PYTHON_SNIPPET_INVALID` | Source token reference.<br>f"task '{task_id}' python -c snippet is not valid Python" | `src/cccc/ralph/filesystem_validator.py:869`<br>`src/cccc/ralph/filesystem_validator.py:870` |
| `W_VERIFICATION_REDUNDANT_PYCOMPILE` | Source token reference.<br>f"task '{task_id}' verification uses redundant py_compile on '{target}'" | `src/cccc/ralph/filesystem_validator.py:839`<br>`src/cccc/ralph/filesystem_validator.py:840` |
| `W_VERIFICATION_ROLE_CLAIMS_SOURCE` | Source token reference.<br>f"task '{task.id}' has role='verification' but claims source path '{offending_path}'" | `src/cccc/ralph/validation_rules/structural.py:871`<br>`src/cccc/ralph/validation_rules/structural.py:872` |
| `W_VERIFICATION_ROLE_NO_COVERS` | Source token reference.<br>f"task '{task.id}' has role='verification' but no verification covers.tasks" | `src/cccc/ralph/validation_rules/structural.py:856`<br>`src/cccc/ralph/validation_rules/structural.py:857` |
| `W_VERIFICATION_SHALLOW_CHECKS` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:266` |
| `W_VERIFICATION_SHAPE_UNKNOWN` | Source token reference.<br>f"task '{task_id}' pytest command has no static target"<br>f"task '{task_id}' pytest target '{file_path}' could not be parsed statically"<br>f"task '{task_id}' pytest target '{target}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet shape not recognized"<br>f"task '{task_id}' verification command could not be parsed"<br>f"task '{task_id}' verification command empty after unwrap"<br>f"task '{task_id}' verification shape not recognized for static precheck" | `src/cccc/ralph/filesystem_validator.py:1013`<br>`src/cccc/ralph/filesystem_validator.py:1014`<br>`src/cccc/ralph/filesystem_validator.py:1045`<br>`src/cccc/ralph/filesystem_validator.py:1046`<br>`src/cccc/ralph/filesystem_validator.py:760`<br>`src/cccc/ralph/filesystem_validator.py:761`<br>`src/cccc/ralph/filesystem_validator.py:772`<br>`src/cccc/ralph/filesystem_validator.py:773`<br>`src/cccc/ralph/filesystem_validator.py:798`<br>`src/cccc/ralph/filesystem_validator.py:799`<br>`src/cccc/ralph/filesystem_validator.py:887`<br>`src/cccc/ralph/filesystem_validator.py:888`<br>`src/cccc/ralph/filesystem_validator.py:982`<br>`src/cccc/ralph/filesystem_validator.py:983` |
| `W_VERIFICATION_TARGET_MISSING` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:1106`<br>`src/cccc/ralph/filesystem_validator.py:1107` |
| `W_VERIFICATION_TOCTOU_GAP` | Source token reference. | `src/cccc/ralph/security_recipes.py:79` |
| `W_VERIFICATION_TRIVIAL_COMMAND` | Source token reference.<br>f"task '{task_id}' verification is trivial command '{base}'" | `src/cccc/ralph/filesystem_validator.py:781`<br>`src/cccc/ralph/filesystem_validator.py:782` |
| `W_WEAK_VERIFICATION_ONLY` | Source token reference.<br>all verifications are compile-level only — no behavioral testing | `src/cccc/ralph/validation_rules/coverage.py:191`<br>`src/cccc/ralph/validation_rules/coverage.py:192` |
## CLI Commands Reference

| Command | Help | Arguments |
| --- | --- | --- |
| `validate` | Check plan for structural issues | `plan`, `-h`, `--format`, `--project-root`, `--tracker`, `--diff`, `--suppress`, `--gate`, `--no-semantic`, `--no-agent`, `--compact`, `--show-schema`, `--ledger`, `--group`, `--generate-security-checks` |
| `suggest` | Show next ready batch | `plan`, `-h`, `--format`, `--ledger`, `--group` |
| `verify` | Run verification for a task | `plan`, `-h`, `--task`, `--changed-files`, `--project-root` |
| `complete` | Mark a task as completed | `plan`, `-h`, `--task`, `--verify`, `--project-root` |
| `explain` | Explain a task or a validation rule code | `plan`, `-h`, `--task`, `--code` |
| `audit` | Audit ledger for operational issues | `-h`, `--ledger`, `--format`, `--days` |
| `sync-state` | Sync completed tasks from ledger to plan | `plan`, `-h`, `--ledger`, `--group` |
| `guide` | Auto-generate capability guide from plan schema and validation rules | `-h`, `--output`, `--update`, `--since` |
| `regression` | Run fixed regression scenarios | `run`, `list`, `-h` |
| `regression run` | Run regression scenarios | `-h`, `--scenario`, `--format` |
| `regression list` | List regression scenarios | `-h` |
| `module` | Run module acceptance commands | `verify`, `-h` |
| `module verify` | Run module acceptance verification | `plan`, `-h`, `--format` |
| `tracker` | Tracker maintenance commands | `archive`, `-h` |
| `tracker archive` | Archive completed tracker sections | `-h`, `--version`, `--tracker`, `--full`, `--dry-run` |
| `flow` | Progressive workflow guidance | `start`, `next`, `status`, `-h` |
| `flow start` | Start a new workflow | `-h`, `--workspace`, `--test-cmd`, `--tracker`, `--guide-output`, `--cccc-root`, `--version`, `--report-path` |
| `flow next` | Advance to next step | `-h`, `--workspace` |
| `flow status` | Show current flow status | `-h`, `--workspace` |

### `ralph validate --help`

```text
usage: ralph validate [-h] [--format {json,text}]
                      [--project-root PROJECT_ROOT] [--tracker TRACKER]
                      [--diff BEFORE AFTER] [--suppress [CODE ...]]
                      [--gate {terminal,branch,repo}] [--no-semantic]
                      [--no-agent] [--compact] [--show-schema]
                      [--ledger LEDGER] [--group GROUP]
                      [--generate-security-checks]
                      [plan]

positional arguments:
  plan                  Path to plan.yaml or plan.json

options:
  -h, --help            show this help message and exit
  --format {json,text}
  --project-root PROJECT_ROOT
                        Project root directory
  --tracker TRACKER     Issue tracker markdown path for acceptance coverage
                        checks
  --diff BEFORE AFTER   Diff two saved validation JSON reports by
                        issue_instance_id
  --suppress [CODE ...]
                        Suppress specific validation codes (e.g.,
                        E_CRITICAL_ENTRYPOINT_UNOWNED)
  --gate {terminal,branch,repo}
                        Apply quality-gate rollout mode for the selected gate
  --no-semantic         Suppress Semantic Findings section in text output
  --no-agent            Skip agent review of beyond-scope issues (pure static
                        mode)
  --compact             Show only errors and high-confidence warnings
                        (suppress hints and low-confidence warnings)
  --show-schema         Print the plan schema (all model fields with types and
                        defaults) and exit
  --ledger LEDGER       Write validation event to this ledger
  --group GROUP         Group ID (resolves ledger path)
  --generate-security-checks
                        Generate behavioral security check commands from
                        critical flows
```

### `ralph suggest --help`

```text
usage: ralph suggest [-h] [--format {json,text}] [--ledger LEDGER]
                     [--group GROUP]
                     plan

positional arguments:
  plan                  Path to plan.yaml or plan.json

options:
  -h, --help            show this help message and exit
  --format {json,text}
  --ledger LEDGER       Read workflow state from this ledger
  --group GROUP         Group ID (resolves ledger path)
```

### `ralph verify --help`

```text
usage: ralph verify [-h] --task TASK [--changed-files [CHANGED_FILES ...]]
                    [--project-root PROJECT_ROOT]
                    plan

positional arguments:
  plan                  Path to plan.yaml or plan.json

options:
  -h, --help            show this help message and exit
  --task TASK           Task ID to verify
  --changed-files [CHANGED_FILES ...]
                        Files changed by this task
  --project-root PROJECT_ROOT
                        Project root directory
```

### `ralph complete --help`

```text
usage: ralph complete [-h] --task TASK [--verify]
                      [--project-root PROJECT_ROOT]
                      plan

positional arguments:
  plan                  Path to plan.yaml or plan.json

options:
  -h, --help            show this help message and exit
  --task TASK           Task ID to mark complete
  --verify              Run verification before completing
  --project-root PROJECT_ROOT
                        Project root directory
```

### `ralph explain --help`

```text
usage: ralph explain [-h] [--task TASK] [--code RULE_CODE] [plan]

positional arguments:
  plan              Path to plan.yaml or plan.json (required with --task)

options:
  -h, --help        show this help message and exit
  --task TASK       Task ID to explain
  --code RULE_CODE  Validation rule code to explain
```

### `ralph audit --help`

```text
usage: ralph audit [-h] --ledger LEDGER [--format {json,text}] [--days DAYS]

options:
  -h, --help            show this help message and exit
  --ledger LEDGER       Path to ledger.jsonl
  --format {json,text}
  --days DAYS           Lookback window in days (default: 7)
```

### `ralph sync-state --help`

```text
usage: ralph sync-state [-h] [--ledger LEDGER] [--group GROUP] plan

positional arguments:
  plan             Path to plan.yaml

options:
  -h, --help       show this help message and exit
  --ledger LEDGER  Path to ledger.jsonl
  --group GROUP    Group ID (resolves ledger path)
```

### `ralph guide --help`

```text
usage: ralph guide [-h] [--output OUTPUT] [--update EXISTING] [--since SINCE]

options:
  -h, --help         show this help message and exit
  --output OUTPUT    Output file (default: stdout)
  --update EXISTING  Incrementally update an existing guide: only regenerate
                     sections affected by git changes
  --since SINCE      Git ref for diff base (default: last commit that touched
                     the guide file)
```

### `ralph regression --help`

```text
usage: ralph regression [-h] {run,list} ...

positional arguments:
  {run,list}
    run       Run regression scenarios
    list      List regression scenarios

options:
  -h, --help  show this help message and exit
```

### `ralph regression run --help`

```text
usage: ralph regression run [-h] [--scenario SCENARIO] [--format {json,text}]

options:
  -h, --help            show this help message and exit
  --scenario SCENARIO   Scenario ID to run (repeatable)
  --format {json,text}
```

### `ralph regression list --help`

```text
usage: ralph regression list [-h]

options:
  -h, --help  show this help message and exit
```

### `ralph module --help`

```text
usage: ralph module [-h] {verify} ...

positional arguments:
  {verify}
    verify    Run module acceptance verification

options:
  -h, --help  show this help message and exit
```

### `ralph module verify --help`

```text
usage: ralph module verify [-h] [--format {json,text}] plan

positional arguments:
  plan                  Path to plan.yaml or plan.json

options:
  -h, --help            show this help message and exit
  --format {json,text}
```

### `ralph tracker --help`

```text
usage: ralph tracker [-h] {archive} ...

positional arguments:
  {archive}
    archive   Archive completed tracker sections

options:
  -h, --help  show this help message and exit
```

### `ralph tracker archive --help`

```text
usage: ralph tracker archive [-h] --version VERSION --tracker TRACKER --full
                             FULL [--dry-run]

options:
  -h, --help         show this help message and exit
  --version VERSION  Version tag
  --tracker TRACKER  Short tracker path
  --full FULL        Full tracker path
  --dry-run          Show what would move without writing files
```

### `ralph flow --help`

```text
usage: ralph flow [-h] {start,next,status} ...

positional arguments:
  {start,next,status}
    start              Start a new workflow
    next               Advance to next step
    status             Show current flow status

options:
  -h, --help           show this help message and exit
```

### `ralph flow start --help`

```text
usage: ralph flow start [-h] --workspace WORKSPACE [--test-cmd TEST_CMD]
                        [--tracker TRACKER] [--guide-output GUIDE_OUTPUT]
                        [--cccc-root CCCC_ROOT] [--version VERSION]
                        [--report-path REPORT_PATH]
                        {solve,e2e}

positional arguments:
  {solve,e2e}           Flow type

options:
  -h, --help            show this help message and exit
  --workspace WORKSPACE
                        Workspace directory
  --test-cmd TEST_CMD   Test command for verification step
  --tracker TRACKER     Issue tracker file
  --guide-output GUIDE_OUTPUT
                        Capability guide output path
  --cccc-root CCCC_ROOT
                        CCCC project root (e2e)
  --version VERSION     Version tag (e2e)
  --report-path REPORT_PATH
                        E2E report output path
```

### `ralph flow next --help`

```text
usage: ralph flow next [-h] [--workspace WORKSPACE]

options:
  -h, --help            show this help message and exit
  --workspace WORKSPACE
                        Workspace directory
```

### `ralph flow status --help`

```text
usage: ralph flow status [-h] [--workspace WORKSPACE]

options:
  -h, --help            show this help message and exit
  --workspace WORKSPACE
                        Workspace directory
```
## Foreman Operational Guidance

### Behavioral Verification Requirements

Implementation tasks MUST include at least one behavioral verification check. A behavioral check exercises the changed runtime behavior directly, for example:

- calling an endpoint and asserting the expected status code or response body
- running a CLI command and asserting the expected state transition
- executing an integration path and asserting the expected side effect

Import-only, compile-only, lint-only, or `py_compile`-only verification is insufficient for feature tasks. If the task changes externally visible behavior, the verification plan should include at least one check that proves the changed path works at runtime.

### Load Balancing - Use `--auto-dispatch` Without `--assignment-map`

When submitting workflows, use:

```bash
cccc workflow submit --auto-dispatch
```

Do not combine `--auto-dispatch` with `--assignment-map`.

Reason:

- `agent_pool.create_or_reuse_agent()` already performs batch-internal load balancing.
- `assign_agent()` updates `_active_assignments` after each allocation.
- The next task in the same batch automatically skips agents that are already busy.
- `--assignment-map` still preserves the foreman's explicit actor choice, but the controller now checks the pool's runtime/model suggestion and warns on mismatches.

Operationally, this means explicit `assignment-map` submissions can still serialize or pin work unnecessarily, while plain `--auto-dispatch` keeps per-batch allocation adaptive.

Note: CLI help text for `--assignment-map` is not updated in this change.

### Manual Actor Creation - Run `cccc model suggest` First

Before manually creating workers with `cccc actor add`, run:

```bash
cccc model suggest plan.yaml
```

or, for a single task category:

```bash
cccc model suggest backend
```

Use the suggested runtime/model as the default when creating actors. Override it only when there is a concrete reason, and record that reason in the workflow notes or retrospective.

### Worker Count - `estimated_parallelism`

After running `ralph suggest`, check `estimated_parallelism` in the output. Create at least that many workers for the batch whenever possible.

If fewer workers are available than `estimated_parallelism`, independent tasks may serialize even though Ralph identified them as parallelizable. If you intentionally run with fewer workers, record that constraint explicitly so the slower completion time is not misread as a dependency bottleneck.

### Multi-Role Agent Team

Recommended operating roles:

| Role | Primary responsibility |
| --- | --- |
| `executor` | Implementation and scoped code changes |
| `reviewer` | Code quality and security review |
| `fixer` | Repair after verification failures |
| `integrator` | Cross-module integration testing and glue verification |

Guidelines:

- more than 5 tasks: add a `reviewer`
- security-sensitive requirements: add a `security-reviewer`
- verification failures or repeated red builds: add a `fixer`
- cross-module changes or dependency-heavy batches: add an `integrator`

The base team does not need every role on every workflow, but larger or riskier batches should not rely on a single implementation-only agent.

### Evaluation Loop

After task completion, Foreman should rate agent performance:

```bash
cccc model rate <model> --rating <1-5> [--registry PATH]
```

Use `--notes` to capture the reason for the score, such as correctness, speed, review quality, or repair burden. This feedback loop feeds future model selection, so skipping ratings removes one of the main signals Foreman can use to improve later assignments.

### Model Selection Rules

**Runtime 只有两个：`codex` 和 `claude`。创建 worker 时必须按以下规则选择 runtime：**

1. **`codex` 是默认 runtime** — 后端、API、逻辑、数据库、测试等任务一律用 `--runtime codex`
2. **`claude` 仅限两类场景** — (a) 非执行角色：security-reviewer、reviewer（纯审查、不写代码）；(b) 前端/审美任务：需要 UI 设计感、CSS 审美、前端体验判断时
3. **`gemini` 不使用**

违反规则的常见错误：看到任务"比较复杂"就给 worker 用 claude — 不要这样做。codex 的代码执行、逻辑推理、debug 能力足够强，复杂度不是换 claude 的理由。

| Runtime | 适用场景 | 说明 |
| --- | --- | --- |
| `codex` | 后端、API、逻辑、测试、重构、集成 | 主力执行，综合能力强，成本低 |
| `claude` | 安全审查、代码审查、前端/审美 | 方案判断、审美、深度推理 |
| `gemini` | — | 不使用 |

创建 worker 前，运行 `cccc model list` 查看当前可用模型和评价。只有 `enabled: true` 的模型可以用作 worker runtime。

### FTS5 CJK Best Practices

`FTS5 MATCH` does not natively provide reliable CJK substring matching. Plain `MATCH` is therefore not enough if the requirement includes Chinese, Japanese, or Korean substring search behavior.

Use one of these strategies explicitly:

- configure an ICU tokenizer
- use a `jieba`-based custom tokenizer
- accept a `LIKE` fallback and document the tradeoff

Plan templates should note CJK search limitations up front. Do not claim CJK substring support unless the tokenizer strategy is specified and verified with representative queries.

### JWT Default Key Detection

Aegis verification should detect default JWT secrets in config files, including values such as `change-me-in-production`.

During the verification phase:

- scan config files and environment templates for default or placeholder JWT secrets
- emit a warning if a default secret is still present
- keep the warning visible even if other verification checks pass

This check belongs in verification because default-key drift is easy to miss during implementation and should surface before deployment.

## v56 新增能力（2026-06-05）

### validate 规则

| 规则代码 | Issue | 检测能力 |
| --- | --- | --- |
| `W_SIGNOFF_CHECK_NON_REQUIRED`（增强） | `RV-38` | `required=false` 的 signoff check 不再被视为有效结构化校验 |
| `W_STATUS_CODE_IMPLEMENTATION_DRIFT` | `RV-39` | 检测 plan `goal_behavior` 中声明的 HTTP 状态码与源码实际返回值的漂移 |
| `W_AF_VERIFICATION_GATE_BYPASS` | `RV-41` | 检测 AF 相关 task 修改引擎路径但未引用 `VerificationGate` |
| `E_AGENT_PROMPT_DIRECT_MODIFICATION` | `RV-43b` | 检测 agent prompt 直接变更绕过 promotion 流程 |
| `W_AF_SILENT_LEGACY_FALLBACK` 等 7 条 | `RV-47` | AgentFlow 架构不变量检测（引擎 fallback、patch 覆盖、gate 权威、acquire 协议、promotion、trace 错误、lease 释放） |
| `W_INTEGRATION_NO_PRODUCTION_CALL_EVIDENCE` | `RV-48` | 检测集成 task 的 `claimed_paths` 是否在生产代码中有调用证据（排除仅测试 import） |

### flow/evaluation 改进

| Issue | 改进内容 |
| --- | --- |
| `FL-63` | `test_stats_reliable` 自动检测项目是否安装 `pytest-randomly` 插件，不再依赖 foreman 自述 |
| `FL-64` | `forbidden_flow` 注入向量字段覆盖验证增强：支持 `is_xxx`、`field=value`、`MUST NOT accept` 模式提取，分层判断测试文件中是否断言字段边界 |
| `FL-65` | `WORKFLOW_EVALUATION.md` 的 `independently_reviewed` 计数现在附带 task ID 列表，支持审计追溯 |
| `FL-66` | solve flow step-4 gap check 增加主路径接入关键词 + 证据验证（入口函数到新模块的调用链路检查） |
| `UX-23` | `WORKFLOW_EVALUATION.md` 初始生成不再写入占位符文本；新增 `W_EVALUATION_PLACEHOLDER_REMAINING` 规则检测残留占位符 |

### AF 引擎真正接入 orchestrator

v56 将 AgentFlow 引擎从标记层提升为真实执行路径。

**环境变量控制：**

- `CCCC_AF_ENGINE_ENABLED=0`（默认）-> legacy 执行引擎
- `CCCC_AF_ENGINE_ENABLED=1` + AF 可用 -> AF 执行引擎

**执行架构：**

- `PlanCompiler` 将 plan tasks 编译为 `ExecutionBundle`，使用 `TaskRef`-compatible adapter 保真传递语义字段
- `AFExecutionEngine` 支持 per-workflow 隔离存储，中间状态报告为 `assigned -> running -> verifying -> completed`
- `CCCCActorRunner` 通过 `agent_pool`、`actor_gateway`、`event_stream` 执行，缺少依赖时报错，不静默 stub
- AF 分支嵌入 assignment controller 流程，保留注册、决策、状态跟踪，仅切换执行引擎层
- `AF -> CCCC` completion envelope 包含完整字段：`attempt_id`、`agent_id`、`changed_files`、`evidence`
- `VerificationGate` 保持最终权威：`af.node_completed -> verification_requested -> VerificationGate`

**两段式 fallback：**

- Pre-dispatch（未派发节点）：AF 不可用时安全回退到 legacy，并记录 `execution_engine_unavailable`
- Mid-execution（已有节点执行）：AF 异常时 fail loud，禁止整批重跑到 legacy，避免重复派发或 lease 错乱

**已解决阻塞问题：**

- `RV-AF-01`：per-workflow bundle 存储，并发 workflow 隔离
- `RV-AF-02`：状态机扩展，支持 `assigned`、`running`、`verifying`、`completed`、`failed` 与 `failure_category`
- `RV-AF-03`：`CCCCActorRunner` 真实依赖对接 `agent_pool`、`actor_gateway`、`event_stream`
- `RV-AF-04`：`PlanCompiler` `TaskRef` adapter + `VerificationSpec` `covers` 字段

## v58 新增 validate 规则

### 流程改进

- **`FL-67`**：plan.yaml `state` 段现在记录 `foreman_override` 完成的任务
- **`FL-68`**：`W_SECURITY_REVIEW_NOT_INDEPENDENT`，检测安全审查任务是否由独立角色执行
- **`FL-69`**：越界告警豁免 `__init__.py`、`conftest.py` 等共享文件
- **`FL-70`**：`WORKFLOW_EVALUATION` 自动提取过程摩擦事件（`task_failed` / `foreman_override` / `scope` 告警）

### validate 检测能力增强

- **`RV-49`**：`W_FORBIDDEN_FLOW_FIELD_ASSERTION_MISSING`，`forbidden_flow` 字段三态检测（`unseen` / `seen` / `asserted`）
- **`RV-50`**：`W_INTEGRATION_IMPORT_ONLY_NO_CALL`，import-only 弱证据降级
- **`RV-51`**：AF/promotion 绕过检测增加结构化证据（`depends_on` / `covers` / `provides-consumes`）
- **`RV-52`**：gap check 结构化记录格式要求（issue ID + 检测类型 + 描述）
- **`RV-53`**：`W_AUTH_TYPE_CAST_UNGUARDED`，认证边界畸形输入覆盖检测（双 token 判定）
- **`RV-54`**：`W_STATE_MACHINE_CONCURRENCY_UNVERIFIED`，状态机并发安全覆盖检测

### AF 架构改进

- **`RV-AF-05`**：`PlanCompiler` `TaskRef` adapter 输入验证 + 依赖引用检查 + `CCCCNodeMeta` 便捷属性
- **`RV-AF-06`**：`ExecutionBundle` `engine_preference` 全链路传播（Plan -> Bundle -> IPC -> Engine 双向拒绝）

## v59 假完成修复（2026-06-06）

- **`FC-1`**：`codex` 是默认执行 runtime；未指定 runtime 时在 `agent_pool` 和 `assignment_actor_registration` 统一兜底到 `codex`，`claude` 仅用于显式审查/前端审美。
- **`FC-2`**：模型选择严格尊重 `enabled` 字段，`enabled=false` 的模型不会被 `select_model_for_task` 选中。
- **`FC-3`**：AF -> legacy 回退不再静默；回退分支会发出 `workflow.af_fallback` ledger 事件并附带原因。
- **`FC-4`**：`WORKFLOW_EVALUATION.md` 定性章节为空时会阻断 `workflow.completed`，并发出 `workflow.evaluation_incomplete` 事件。
- **`FC-5`**：已验证（生效）项归档必须在归档段落提供 E2E 行为确认证据，否则 `improvement-register` 检查阻断。

## 已知局限更新

以下项目已从“已知局限”移至“已实现”：

- ~~`RV-38`~~：已实现（v56 T1）
- ~~`RV-41`~~：已实现（v56 T4）
- ~~`RV-43b`~~：已实现（v56 T5）
- ~~`RV-47`~~：已实现（v56 T6，7 条子规则）
- ~~`RV-49`~~：已实现（v58 validate 检测能力增强）
- ~~`RV-50`~~：已实现（v58 validate 检测能力增强）
- ~~`RV-51`~~：已实现（v58 validate 检测能力增强）
- ~~`RV-52`~~：已实现（v58 validate 检测能力增强）
- ~~`RV-AF-05`~~：已实现（v58 AF 架构改进）
- ~~`RV-AF-06`~~：已实现（v58 AF 架构改进）

### v56 已知局限（Codex review 发现，已在 v58 解决）

- ~~`RV-49`~~：`forbidden_flow` 字段覆盖检测仅查命令文本，不查测试断言，已由字段三态检测补齐证据面
- ~~`RV-50`~~：集成证据检测原先以 import 存在性代替调用路径，已降级 import-only 弱证据
- ~~`RV-51`~~：AF/promotion 绕过检测原先依赖文本关键词，已补充结构化证据
- ~~`RV-52`~~：`FL-66` gap check 原先缺少结构化记录要求，已补充 issue ID + 检测类型 + 描述格式
- ~~`RV-AF-05`~~：`PlanCompiler` raw dict 丢失 `TaskRef` 语义，已补上 adapter 输入验证与依赖引用检查
- ~~`RV-AF-06`~~：AF -> legacy fallback 与架构红线冲突，已改为 `engine_preference` 全链路传播与双向拒绝

### v58 已知局限（CG 审查发现）

- **`RV-55`**：安全审查独立性规则与 independent review 规则证据面脱节
- **`RV-56`**：`forbidden_flow` 三态检测仍有正向出现绕过风险
- **`RV-57`**：AF gate bypass 和 authority 两条规则证据源不完全一致
- **`RV-58`**：auth 边界检测与现有 RBAC 规则共用证据面
- **`RV-59`**：并发安全检测可被填写关键词绕过
- **`RV-60`**：`TaskRef` adapter 缺少 `expected_input` / `expected_output` 字段
- **`RV-61`**：`engine_preference` 全链路传播缺少中间节点对称校验















