# Ralph Capability Guide

## Plan Schema Fields

### Plan
- Path: `top level`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `schema_version` | `Optional` | `None` |  |
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

## Validation Rules Reference

| Code | Description | Source |
| --- | --- | --- |
| `E_AEGIS_PLACEHOLDER_CONTENT` | Source token reference.<br>f"task '{task.id}' contains placeholder content in {field_name}" | `src/cccc/ralph/validation_rules/discipline.py:58`<br>`src/cccc/ralph/validation_rules/discipline.py:60` |
| `E_AEGIS_RETIREMENT_TRACK_MISSING` | Source token reference.<br>f"{intent} task '{task.id}' has patch-shape risk without retirement_track" | `src/cccc/ralph/validation_rules/discipline.py:79`<br>`src/cccc/ralph/validation_rules/discipline.py:81` |
| `E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW` | Source token reference.<br>f"task '{task.id}' modifies ripple-prone paths but verification only covers itself" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:108`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:110` |
| `E_AEGIS_SECURITY_CHAIN_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:11` |
| `E_AGENT_REVIEW_FAILED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_CONSUMER_FROM_UNKNOWN` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'" | `src/cccc/ralph/validation_rules/contracts.py:55`<br>`src/cccc/ralph/validation_rules/contracts.py:56` |
| `E_CONSUMER_WITHOUT_PROVIDER` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' but no task provides it" | `src/cccc/ralph/validation_rules/contracts.py:45`<br>`src/cccc/ralph/validation_rules/contracts.py:46` |
| `E_COVERS_UNKNOWN_FLOW` | Source token reference.<br>f"task '{task.id}' covers flow '{flow_id}' which is not declared in critical_flows or forbidden_flows" | `src/cccc/ralph/validation_rules/coverage.py:1184`<br>`src/cccc/ralph/validation_rules/coverage.py:1185` |
| `E_COVERS_UNKNOWN_TASK` | Source token reference.<br>f"task '{task.id}' covers unknown task '{covered_id}'" | `src/cccc/ralph/validation_rules/structural.py:176`<br>`src/cccc/ralph/validation_rules/structural.py:177` |
| `E_COVERS_WITHOUT_DEP_ORDER` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but '{covered_id}' is not in its transitive dependency closure" | `src/cccc/ralph/validation_rules/structural.py:188`<br>`src/cccc/ralph/validation_rules/structural.py:189` |
| `E_CRITICAL_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:525`<br>`src/cccc/ralph/validation_rules/coverage.py:526` |
| `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:592`<br>`src/cccc/ralph/validation_rules/coverage.py:593` |
| `E_CRITICAL_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"critical flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:736`<br>`src/cccc/ralph/validation_rules/coverage.py:737` |
| `E_CRITICAL_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] critical flow '{flow.id}' is not covered by any task's verification"<br>f"[suppress_flows] critical flow '{flow.id}' is not covered by any task's verification"<br>f"critical flow '{flow.id}' is not covered by any task's verification" | `src/cccc/ralph/validation_rules/coverage.py:1331`<br>`src/cccc/ralph/validation_rules/coverage.py:544`<br>`src/cccc/ralph/validation_rules/coverage.py:545`<br>`src/cccc/ralph/validation_rules/coverage.py:555`<br>`src/cccc/ralph/validation_rules/coverage.py:556`<br>`src/cccc/ralph/validation_rules/coverage.py:566`<br>`src/cccc/ralph/validation_rules/coverage.py:567`<br>`src/cccc/ralph/validation_rules/coverage.py:731` |
| `E_CYCLE_DETECTED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_DEP_CYCLE` | Source token reference.<br>f"dependency cycle detected involving: {', '.join(cycle)}" | `src/cccc/ralph/validation_rules/structural.py:124`<br>`src/cccc/ralph/validation_rules/structural.py:125` |
| `E_DEP_SELF` | Source token reference.<br>f"task '{t.id}' depends on itself" | `src/cccc/ralph/validation_rules/structural.py:114`<br>`src/cccc/ralph/validation_rules/structural.py:115` |
| `E_DEP_UNKNOWN` | Source token reference.<br>f"task '{t.id}' depends on unknown task '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:103`<br>`src/cccc/ralph/validation_rules/structural.py:104` |
| `E_DUPLICATE_FLOW_ID` | Source token reference.<br>f"duplicate critical_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:1249`<br>`src/cccc/ralph/validation_rules/coverage.py:1250` |
| `E_DUPLICATE_FORBIDDEN_FLOW_ID` | Source token reference.<br>f"duplicate forbidden_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:1263`<br>`src/cccc/ralph/validation_rules/coverage.py:1264` |
| `E_DUPLICATE_INVARIANT_NAME` | Source token reference.<br>f"duplicate registration_invariant name '{inv.name}'" | `src/cccc/ralph/validation_rules/coverage.py:1277`<br>`src/cccc/ralph/validation_rules/coverage.py:1278` |
| `E_DUPLICATE_TASK_ID` | Source token reference.<br>f"duplicate task id '{t.id}'" | `src/cccc/ralph/validation_rules/structural.py:91`<br>`src/cccc/ralph/validation_rules/structural.py:92` |
| `E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"forbidden flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:1091`<br>`src/cccc/ralph/validation_rules/coverage.py:1092` |
| `E_FORBIDDEN_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] forbidden flow '{flow.id}' has no negative test covering it"<br>f"forbidden flow '{flow.id}' has no negative test covering it" | `src/cccc/ralph/validation_rules/coverage.py:1069`<br>`src/cccc/ralph/validation_rules/coverage.py:1070`<br>`src/cccc/ralph/validation_rules/coverage.py:1080`<br>`src/cccc/ralph/validation_rules/coverage.py:1081` |
| `E_MISSING_CLAIMED_PATHS` | Source token reference.<br>f"task '{t.id}' has no claimed_paths" | `src/cccc/ralph/validation_rules/structural.py:208`<br>`src/cccc/ralph/validation_rules/structural.py:209` |
| `E_MISSING_INTEGRATION_SPINE` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no task provides integration/e2e verification covering multiple tasks' | `src/cccc/ralph/validation_rules/structural.py:695`<br>`src/cccc/ralph/validation_rules/structural.py:696` |
| `E_MISSING_VERIFICATION` | Source token reference.<br>f"task '{t.id}' has no verification defined" | `src/cccc/ralph/validation_rules/structural.py:216`<br>`src/cccc/ralph/validation_rules/structural.py:217` |
| `E_MOCK_TEST_MISSING_NAME` | Source token reference.<br>f"task '{t.id}' has a mock_test with empty name" | `src/cccc/ralph/validation_rules/coverage.py:1020`<br>`src/cccc/ralph/validation_rules/coverage.py:1021` |
| `E_MOCK_TEST_MISSING_VERIFY_COMMAND` | Source token reference.<br>f"task '{t.id}' mock_test '{mt.name}' has no verify_command" | `src/cccc/ralph/validation_rules/coverage.py:1027`<br>`src/cccc/ralph/validation_rules/coverage.py:1028` |
| `E_MODULE_DUPLICATE_ID` | Source token reference.<br>f"task '{task.id}' has duplicate module id '{mod.id}'" | `src/cccc/ralph/validation_rules/structural.py:897`<br>`src/cccc/ralph/validation_rules/structural.py:905`<br>`src/cccc/ralph/validation_rules/structural.py:906` |
| `E_MODULE_UNKNOWN_DEP` | Source token reference.<br>f"task '{task.id}' module '{mod.id}' depends on unknown module '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:897`<br>`src/cccc/ralph/validation_rules/structural.py:916`<br>`src/cccc/ralph/validation_rules/structural.py:917` |
| `E_NO_CROSS_TASK_VERIFICATION` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no integration/e2e verification covers multiple tasks' | `src/cccc/ralph/validation_rules/coverage.py:101`<br>`src/cccc/ralph/validation_rules/coverage.py:102` |
| `E_UNCOVERED_REQUIRED_ISSUE` | Source token reference.<br>f"required issue '{issue_id}' is not addressed by any task" | `src/cccc/ralph/validation_rules/coverage.py:1334`<br>`src/cccc/ralph/validation_rules/coverage.py:792`<br>`src/cccc/ralph/validation_rules/coverage.py:793` |
| `E_VERIFICATION_SHALLOW_CRITICAL` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:162` |
| `E_VERIFICATION_TARGET_MISSING_FILE` | Source token reference.<br>f"task '{task_id}' references missing file '{rel_path}'" | `src/cccc/ralph/filesystem_validator.py:989`<br>`src/cccc/ralph/filesystem_validator.py:990` |
| `E_WRITE_CONFLICT` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:25` |
| `H_DUPLICATE_ISSUE_ADDRESS` | Source token reference.<br>f"issue '{issue_id}' is addressed by multiple tasks: {', '.join(sorted(task_ids))}" | `src/cccc/ralph/validation_rules/coverage.py:988`<br>`src/cccc/ralph/validation_rules/coverage.py:989` |
| `H_MOCK_TESTS_ON_RALPH_MODE` | Source token reference.<br>f"task '{t.id}' has mock_tests but verification_mode='ralph'; mock_tests only run in agent/challenge mode" | `src/cccc/ralph/validation_rules/coverage.py:1009`<br>`src/cccc/ralph/validation_rules/coverage.py:1010` |
| `H_SUPPRESS_UNUSED` | Source token reference.<br>f"suppress_codes entry '{code}' did not match any emitted issue" | `src/cccc/ralph/validation_rules/coverage.py:1311`<br>`src/cccc/ralph/validation_rules/coverage.py:1312` |
| `H_VERIFICATION_COMMAND_DEAD` | Source token reference.<br>f"task '{task.id}' verification.command is ignored in favor of structured checks" | `src/cccc/ralph/validation_rules/coverage.py:208`<br>`src/cccc/ralph/validation_rules/coverage.py:209` |
| `W_ACCEPTANCE_COVERAGE_GAP` | Source token reference.<br>f"issue '{issue_id}' acceptance coverage is {coverage:.2f} ({len(matched_keywords)}/{len(tracker_keywords)} tracker keywords matched)" | `src/cccc/ralph/validation_rules/coverage.py:847`<br>`src/cccc/ralph/validation_rules/coverage.py:848` |
| `W_AEGIS_COMPLEX_MISSING_BASELINE` | Source token reference.<br>f"complex task '{task.id}' has no aegis.baseline_refs" | `src/cccc/ralph/validation_rules/discipline.py:135`<br>`src/cccc/ralph/validation_rules/discipline.py:137` |
| `W_AEGIS_DECISION_HYGIENE_MISSING` | Source token reference.<br>f"task '{task.id}' introduces owner-pattern risk without decision_review" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:58`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:60` |
| `W_AEGIS_DRIFT_CHECK_MISSING` | Source token reference.<br>f"task '{task.id}' has {module_count} modules without aegis.drift_check" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:77`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:79` |
| `W_AEGIS_FIX_NO_REPAIR_TRACK` | Source token reference.<br>f"fix task '{task.id}' has no repair_track" | `src/cccc/ralph/validation_rules/discipline.py:97`<br>`src/cccc/ralph/validation_rules/discipline.py:99` |
| `W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has patch-shape risk without aegis.patch_shape_triage" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:23`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:25` |
| `W_AEGIS_PLAN_NO_COMPAT_BOUNDARY` | Source token reference.<br>plan has cross-task dependencies but no task declares aegis.compat_boundary | `src/cccc/ralph/validation_rules/discipline_second_wave.py:92`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:93` |
| `W_AEGIS_RIPPLE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has ripple risk without downstream awareness_paths" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:41`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:43` |
| `W_AEGIS_TDD_NO_TEST_PATH` | Source token reference.<br>f"{intent} task '{task.id}' claims no test path" | `src/cccc/ralph/validation_rules/discipline.py:116`<br>`src/cccc/ralph/validation_rules/discipline.py:118` |
| `W_AGENT_REVIEW_SKIPPED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `W_AUTH_TIMING_UNSAFE` | Source token reference. | `src/cccc/ralph/security_recipes.py:49` |
| `W_BATCH_E2E_NO_COMMAND` | Source token reference.<br>f"plan has {dep_layers} dependency layers but no batch_e2e_command — cross-task integration won't be verified between batches" | `src/cccc/ralph/validation_rules/coverage.py:1472`<br>`src/cccc/ralph/validation_rules/coverage.py:1482`<br>`src/cccc/ralph/validation_rules/coverage.py:1483` |
| `W_CLAIMED_PATH_INCOMPLETE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:27` |
| `W_CONFTEST_COVERAGE_GAP` | Source token reference.<br>f"task '{task_id}' source '{source_path}' has {count} related conftest(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:234`<br>`src/cccc/ralph/filesystem_validator.py:235`<br>`src/cccc/ralph/filesystem_validator.py:441` |
| `W_CONSUME_WITHOUT_DEP` | Source token reference.<br>f"task '{t.id}' consumes from '{src}' but does not depend on it" | `src/cccc/ralph/validation_rules/contracts.py:160`<br>`src/cccc/ralph/validation_rules/contracts.py:161` |
| `W_CONTRACT_SCHEMA_MISMATCH` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' with an incompatible schema hint" | `src/cccc/ralph/validation_rules/contracts.py:66`<br>`src/cccc/ralph/validation_rules/contracts.py:67` |
| `W_CONTRACT_SIGNATURE_MISMATCH` | Source token reference.<br>f"task '{consumer_task_id}' consumes '{consumer.name}' with signature mismatch" | `src/cccc/ralph/validation_rules/contracts.py:229`<br>`src/cccc/ralph/validation_rules/contracts.py:230` |
| `W_COVERS_CLAIM_UNVERIFIABLE` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification command does not reference any claimed_paths of '{covered_id}'" | `src/cccc/ralph/validation_rules/coverage.py:453`<br>`src/cccc/ralph/validation_rules/coverage.py:454` |
| `W_COVERS_NOT_EXERCISED` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification does not reference the covered paths" | `src/cccc/ralph/validation_rules/coverage.py:232`<br>`src/cccc/ralph/validation_rules/coverage.py:233` |
| `W_CRITICAL_FLOW_NO_ENTRYPOINTS` | Source token reference.<br>f"critical flow '{flow.id}' has no entrypoints declared" | `src/cccc/ralph/validation_rules/coverage.py:1295`<br>`src/cccc/ralph/validation_rules/coverage.py:1296` |
| `W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims critical flow entrypoints but uses verification_mode='{task.verification_mode}' instead of agent/challenge" | `src/cccc/ralph/validation_rules/coverage.py:759`<br>`src/cccc/ralph/validation_rules/coverage.py:760` |
| `W_CROSS_BOUNDARY_WITHOUT_GLUE` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' across different path boundaries, but no integration/e2e verification covers both" | `src/cccc/ralph/validation_rules/structural.py:673`<br>`src/cccc/ralph/validation_rules/structural.py:674` |
| `W_CROSS_TASK_IO_MISMATCH` | Source token reference.<br>f"task '{task.id}' expects input keys {sorted(missing)} not provided by any upstream dependency's expected_output" | `src/cccc/ralph/validation_rules/contracts.py:348`<br>`src/cccc/ralph/validation_rules/contracts.py:370`<br>`src/cccc/ralph/validation_rules/contracts.py:371` |
| `W_DEP_WITHOUT_CONSUME` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' which provides contracts, but does not consume any of them" | `src/cccc/ralph/validation_rules/contracts.py:172`<br>`src/cccc/ralph/validation_rules/contracts.py:173` |
| `W_DISCONNECTED_COMPONENTS` | Source token reference.<br>f'plan has {len(components)} disconnected task groups' | `src/cccc/ralph/validation_rules/structural.py:135`<br>`src/cccc/ralph/validation_rules/structural.py:136` |
| `W_DYNAMIC_TEST_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' source '{source_path}' is dynamically imported by '{test_path}'" | `src/cccc/ralph/filesystem_validator.py:218`<br>`src/cccc/ralph/filesystem_validator.py:432`<br>`src/cccc/ralph/filesystem_validator.py:433` |
| `W_E2E_MISSING_COMPILE_CHECK` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:31` |
| `W_EMPTY_ACCEPTANCE` | Source token reference.<br>f"task '{t.id}' has no acceptance_criteria" | `src/cccc/ralph/validation_rules/structural.py:224`<br>`src/cccc/ralph/validation_rules/structural.py:225` |
| `W_FINDING_REF_INCOMPLETE` | Source token reference.<br>f"finding_ref '{ref.id}' is missing mitigation"<br>finding_ref is missing id | `src/cccc/ralph/validation_rules/coverage.py:1112`<br>`src/cccc/ralph/validation_rules/coverage.py:1113`<br>`src/cccc/ralph/validation_rules/coverage.py:1119`<br>`src/cccc/ralph/validation_rules/coverage.py:1120` |
| `W_FINDING_REF_UNKNOWN_ENFORCER` | Source token reference.<br>f"finding_ref '{ref.id}' references unknown enforcer '{enforcer}'" | `src/cccc/ralph/validation_rules/coverage.py:1128`<br>`src/cccc/ralph/validation_rules/coverage.py:1129` |
| `W_FLOW_OWNER_NO_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims entrypoint '{entrypoint}' of flow '{flow.id}' but doesn't verify the flow" | `src/cccc/ralph/validation_rules/coverage.py:699`<br>`src/cccc/ralph/validation_rules/coverage.py:700` |
| `W_FLOW_SEGMENT_UNOWNED` | Source token reference.<br>f"task '{task.id}' covers flow '{flow.id}' but doesn't claim any of its entrypoints" | `src/cccc/ralph/validation_rules/coverage.py:682`<br>`src/cccc/ralph/validation_rules/coverage.py:683` |
| `W_FTS_CJK_SUBSTRING_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:13` |
| `W_GLOBAL_WRITE_CLAIM` | Source token reference.<br>f"task '{t.id}' claims global write ('/') — blocks all parallel tasks" | `src/cccc/ralph/validation_rules/structural.py:245`<br>`src/cccc/ralph/validation_rules/structural.py:246` |
| `W_GOAL_CJK_TOKENIZATION_HINT` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:30` |
| `W_GOAL_REFERENCES_UNCLAIMED_PATH` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:28` |
| `W_GOAL_SYMBOL_NOT_IN_CLAIMED_PATH` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:29` |
| `W_INDIRECT_TEST_IMPORT` | Source token reference.<br>f"task '{task_id}' has {len(entries)} indirect test import hint(s) not covered by any verification; showing first {len(samples)} sample(s)"<br>f"task '{task_id}' source '{source_path}' has {count} related test(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:477`<br>`src/cccc/ralph/filesystem_validator.py:478`<br>`src/cccc/ralph/filesystem_validator.py:494`<br>`src/cccc/ralph/filesystem_validator.py:495` |
| `W_INTEGRATION_INTERFACE_MISMATCH` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' but verification does not reference any of {contract.from_task}'s paths" | `src/cccc/ralph/validation_rules/contracts.py:124`<br>`src/cccc/ralph/validation_rules/contracts.py:125` |
| `W_INTEGRATION_ROLE_WEAK_VERIFICATION` | Source token reference.<br>f"task '{task.id}' has role='integration' but lacks integration/e2e verification covering at least 2 tasks" | `src/cccc/ralph/validation_rules/structural.py:728`<br>`src/cccc/ralph/validation_rules/structural.py:729` |
| `W_INTEGRATION_TASK_SHALLOW_VERIFICATION` | Source token reference.<br>f"task '{task.id}' integration verification is shallow and lacks a behavioral check" | `src/cccc/ralph/validation_rules/coverage.py:190`<br>`src/cccc/ralph/validation_rules/coverage.py:191` |
| `W_ISOLATED_TASK` | Source token reference.<br>f"task '{t.id}' has no dependency edges (neither depends on others nor depended upon)" | `src/cccc/ralph/validation_rules/structural.py:151`<br>`src/cccc/ralph/validation_rules/structural.py:152` |
| `W_LEAF_ROLE_IS_INTEGRATOR` | Source token reference.<br>f"task '{task.id}' has role='leaf' but provides integration/e2e verification covering multiple tasks" | `src/cccc/ralph/validation_rules/structural.py:768`<br>`src/cccc/ralph/validation_rules/structural.py:769` |
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | Source token reference.<br>all cross-task integration/e2e verifiers are sink tasks and appear late in the graph | `src/cccc/ralph/validation_rules/structural.py:808`<br>`src/cccc/ralph/validation_rules/structural.py:809` |
| `W_NO_FAILURE_PATH` | Source token reference.<br>f"task '{t.id}' involves assignment/actor operations but has no failure handling description or failure_path field" | `src/cccc/ralph/validation_rules/coverage.py:291`<br>`src/cccc/ralph/validation_rules/coverage.py:292` |
| `W_PLAN_SCOPE_UNUSED` | Source token reference.<br>f"registration invariant '{inv.name}' references '{inv.registry_file}' which is not claimed by any task" | `src/cccc/ralph/validation_rules/coverage.py:1349`<br>`src/cccc/ralph/validation_rules/coverage.py:1350` |
| `W_PROVIDER_UNUSED` | Source token reference.<br>f"contract '{name}' is provided but never consumed" | `src/cccc/ralph/validation_rules/contracts.py:92`<br>`src/cccc/ralph/validation_rules/contracts.py:93` |
| `W_REGISTRATION_INVARIANT_UNCOVERED` | Source token reference.<br>f"registration invariant '{inv.name}' registry file '{inv.registry_file}' is not claimed by any task" | `src/cccc/ralph/filesystem_validator.py:313`<br>`src/cccc/ralph/filesystem_validator.py:314` |
| `W_SHARED_FILE_PARTIAL_VERIFICATION` | Source token reference.<br>f"tasks '{t1.id}' and '{t2.id}' share paths but neither verification mentions them" | `src/cccc/ralph/validation_rules/structural.py:625`<br>`src/cccc/ralph/validation_rules/structural.py:626` |
| `W_SHARED_PATH_NO_DEPENDENCY` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:26` |
| `W_SILENT_DEGRADATION_UNCHECKED` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:14` |
| `W_SSRF_ENCODING_UNCOVERED` | Source token reference. | `src/cccc/ralph/security_recipes.py:39` |
| `W_SSRF_ROUTE_BINDING_MISSING` | Source token reference. | `src/cccc/ralph/validation_rules/discipline_security.py:12` |
| `W_STATE_UNKNOWN_TASK_REF` | Source token reference.<br>f"state.completed_task_ids references unknown task '{tid}'"<br>f"state.failed_task_ids references unknown task '{tid}'"<br>f"state.running_tasks references unknown task '{rt.task_id}'" | `src/cccc/ralph/validation_rules/coverage.py:1204`<br>`src/cccc/ralph/validation_rules/coverage.py:1205`<br>`src/cccc/ralph/validation_rules/coverage.py:1216`<br>`src/cccc/ralph/validation_rules/coverage.py:1217`<br>`src/cccc/ralph/validation_rules/coverage.py:1228`<br>`src/cccc/ralph/validation_rules/coverage.py:1229` |
| `W_SUPPRESS_FLOWS_UNKNOWN` | Source token reference.<br>f"suppress_flows references unknown flow '{flow_id}'" | `src/cccc/ralph/validation_rules/coverage.py:1144`<br>`src/cccc/ralph/validation_rules/coverage.py:1145` |
| `W_TASK_ADDRESSES_DISJOINT` | Source token reference.<br>f"task '{t.id}' addresses issues from different domains: {', '.join(sorted(prefixes))}" | `src/cccc/ralph/validation_rules/coverage.py:970`<br>`src/cccc/ralph/validation_rules/coverage.py:971` |
| `W_TEST_COVERAGE_GAP` | Source code assignment literal.<br>Source token reference. | `src/cccc/ralph/filesystem_validator.py:243`<br>`src/cccc/ralph/filesystem_validator.py:441` |
| `W_TOKEN_TYPE_CONFUSION_UNCOVERED` | Source token reference. | `src/cccc/ralph/security_recipes.py:67` |
| `W_UNCLAIMED_TEST_FOR_SOURCE` | Source token reference.<br>f"task '{task.id}' source '{source_path}' has related test '{test_path}' claimed by no task" | `src/cccc/ralph/filesystem_validator.py:356`<br>`src/cccc/ralph/filesystem_validator.py:357` |
| `W_UNKNOWN_VERIFICATION_MODE` | Source token reference.<br>f"task '{t.id}' has unknown verification_mode '{t.verification_mode}'" | `src/cccc/ralph/validation_rules/structural.py:234`<br>`src/cccc/ralph/validation_rules/structural.py:235` |
| `W_VERIFICATION_BEHAVIOR_MISMATCH` | Source token reference.<br>f"task '{t.id}' goal implies runtime behavior but verification is only {v.level}-level" | `src/cccc/ralph/validation_rules/coverage.py:346`<br>`src/cccc/ralph/validation_rules/coverage.py:347` |
| `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` | Source token reference.<br>f"task '{task_id}' verification contains shell operators and was skipped" | `src/cccc/ralph/filesystem_validator.py:598`<br>`src/cccc/ralph/filesystem_validator.py:599` |
| `W_VERIFICATION_CROSS_SCOPE` | Source token reference.<br>f"task '{task.id}' verification check '{check.name}' references path '{ref_path}' which belongs to task '{other_id}'"<br>f"task '{task.id}' verification command references path '{ref_path}' which belongs to task '{other_id}'" | `src/cccc/ralph/validation_rules/coverage.py:387`<br>`src/cccc/ralph/validation_rules/coverage.py:388`<br>`src/cccc/ralph/validation_rules/coverage.py:413`<br>`src/cccc/ralph/validation_rules/coverage.py:414` |
| `W_VERIFICATION_DUPLICATE_COMMAND` | Source token reference.<br>f'tasks {task_ids} share the same verification command' | `src/cccc/ralph/validation_rules/coverage.py:319`<br>`src/cccc/ralph/validation_rules/coverage.py:320` |
| `W_VERIFICATION_IMPORT_MODULE_MISSING` | Source token reference.<br>f"task '{task_id}' imports module '{module_name}' which only the task itself claims (self-verification)"<br>message | `src/cccc/ralph/filesystem_validator.py:1016`<br>`src/cccc/ralph/filesystem_validator.py:1017`<br>`src/cccc/ralph/filesystem_validator.py:1032`<br>`src/cccc/ralph/filesystem_validator.py:1033` |
| `W_VERIFICATION_IMPORT_SYMBOL_MISSING` | Source token reference.<br>f"task '{task_id}' imports missing symbol '{alias.name}' from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:818`<br>`src/cccc/ralph/filesystem_validator.py:819` |
| `W_VERIFICATION_NO_CHECKS` | Source token reference.<br>f"task '{t.id}' has a verification command but no structured checks — consider splitting into at least a compile check and a behavior test check" | `src/cccc/ralph/validation_rules/coverage.py:131`<br>`src/cccc/ralph/validation_rules/coverage.py:132` |
| `W_VERIFICATION_PYTEST_K_NO_MATCH` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:930`<br>`src/cccc/ralph/filesystem_validator.py:931` |
| `W_VERIFICATION_PYTEST_NODE_MISSING` | Source token reference.<br>f"task '{task_id}' pytest target node '{node_part}' was not found in '{file_path}'" | `src/cccc/ralph/filesystem_validator.py:887`<br>`src/cccc/ralph/filesystem_validator.py:888` |
| `W_VERIFICATION_PYTHON_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' import target '{module_name}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet is opaque to static import checks"<br>f"task '{task_id}' python -c uses relative or opaque imports"<br>f"task '{task_id}' uses wildcard import from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:745`<br>`src/cccc/ralph/filesystem_validator.py:746`<br>`src/cccc/ralph/filesystem_validator.py:769`<br>`src/cccc/ralph/filesystem_validator.py:770`<br>`src/cccc/ralph/filesystem_validator.py:797`<br>`src/cccc/ralph/filesystem_validator.py:798`<br>`src/cccc/ralph/filesystem_validator.py:808`<br>`src/cccc/ralph/filesystem_validator.py:809` |
| `W_VERIFICATION_PYTHON_SNIPPET_INVALID` | Source token reference.<br>f"task '{task_id}' python -c snippet is not valid Python" | `src/cccc/ralph/filesystem_validator.py:734`<br>`src/cccc/ralph/filesystem_validator.py:735` |
| `W_VERIFICATION_REDUNDANT_PYCOMPILE` | Source token reference.<br>f"task '{task_id}' verification uses redundant py_compile on '{target}'" | `src/cccc/ralph/filesystem_validator.py:704`<br>`src/cccc/ralph/filesystem_validator.py:705` |
| `W_VERIFICATION_ROLE_CLAIMS_SOURCE` | Source token reference.<br>f"task '{task.id}' has role='verification' but claims source path '{offending_path}'" | `src/cccc/ralph/validation_rules/structural.py:758`<br>`src/cccc/ralph/validation_rules/structural.py:759` |
| `W_VERIFICATION_ROLE_NO_COVERS` | Source token reference.<br>f"task '{task.id}' has role='verification' but no verification covers.tasks" | `src/cccc/ralph/validation_rules/structural.py:743`<br>`src/cccc/ralph/validation_rules/structural.py:744` |
| `W_VERIFICATION_SHALLOW_CHECKS` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:164` |
| `W_VERIFICATION_SHAPE_UNKNOWN` | Source token reference.<br>f"task '{task_id}' pytest command has no static target"<br>f"task '{task_id}' pytest target '{file_path}' could not be parsed statically"<br>f"task '{task_id}' pytest target '{target}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet shape not recognized"<br>f"task '{task_id}' verification command could not be parsed"<br>f"task '{task_id}' verification command empty after unwrap"<br>f"task '{task_id}' verification shape not recognized for static precheck" | `src/cccc/ralph/filesystem_validator.py:608`<br>`src/cccc/ralph/filesystem_validator.py:609`<br>`src/cccc/ralph/filesystem_validator.py:620`<br>`src/cccc/ralph/filesystem_validator.py:621`<br>`src/cccc/ralph/filesystem_validator.py:646`<br>`src/cccc/ralph/filesystem_validator.py:647`<br>`src/cccc/ralph/filesystem_validator.py:752`<br>`src/cccc/ralph/filesystem_validator.py:753`<br>`src/cccc/ralph/filesystem_validator.py:847`<br>`src/cccc/ralph/filesystem_validator.py:848`<br>`src/cccc/ralph/filesystem_validator.py:878`<br>`src/cccc/ralph/filesystem_validator.py:879`<br>`src/cccc/ralph/filesystem_validator.py:910`<br>`src/cccc/ralph/filesystem_validator.py:911` |
| `W_VERIFICATION_TARGET_MISSING` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:971`<br>`src/cccc/ralph/filesystem_validator.py:972` |
| `W_VERIFICATION_TOCTOU_GAP` | Source token reference. | `src/cccc/ralph/security_recipes.py:79` |
| `W_VERIFICATION_TRIVIAL_COMMAND` | Source token reference.<br>f"task '{task_id}' verification is trivial command '{base}'" | `src/cccc/ralph/filesystem_validator.py:629`<br>`src/cccc/ralph/filesystem_validator.py:630` |
| `W_WEAK_VERIFICATION_ONLY` | Source token reference.<br>all verifications are compile-level only — no behavioral testing | `src/cccc/ralph/validation_rules/coverage.py:115`<br>`src/cccc/ralph/validation_rules/coverage.py:116` |
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
