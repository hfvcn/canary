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
| `aegis` | `Optional` | `None` | Aegis execution discipline: intent, repair_track, retirement_track, baseline_refs, compat_boundary, patch_shape_triage, decision_review, drift_check. |
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
| `baseline_refs` | `Optional` | `<factory list>` |  |
| `compat_boundary` | `Optional` | `''` |  |
| `patch_shape_triage` | `Union` | `None` |  |
| `decision_review` | `Union` | `None` |  |
| `drift_check` | `Union` | `None` |  |
| `repair_track` | `Optional` | `None` |  |
| `retirement_track` | `Optional` | `None` |  |

### RepairTrack
- Path: `tasks[].aegis.repair_track`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `root_cause` | `Optional` | `''` |  |
| `canonical_owner` | `Optional` | `''` |  |
| `minimal_change` | `Optional` | `''` |  |
| `verification_method` | `Optional` | `''` |  |

### RetirementTrack
- Path: `tasks[].aegis.retirement_track`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `old_owner` | `Optional` | `''` |  |
| `deletion_trigger` | `Optional` | `''` |  |
| `retained` | `Optional` | `False` |  |
| `retention_reason` | `Optional` | `''` |  |

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
| `E_AEGIS_PLACEHOLDER_CONTENT` | Source token reference.<br>f"task '{task.id}' contains placeholder content in {field_name}" | `src/cccc/ralph/validation_rules/discipline.py:57`<br>`src/cccc/ralph/validation_rules/discipline.py:59` |
| `E_AEGIS_RETIREMENT_TRACK_MISSING` | Source token reference.<br>f"{intent} task '{task.id}' has patch-shape risk without retirement_track" | `src/cccc/ralph/validation_rules/discipline.py:78`<br>`src/cccc/ralph/validation_rules/discipline.py:80` |
| `E_AEGIS_RIPPLE_VERIFICATION_TOO_NARROW` | Source token reference.<br>f"task '{task.id}' modifies ripple-prone paths but verification only covers itself" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:108`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:110` |
| `E_AEGIS_SECURITY_CHECKS_MISSING` | Source token reference.<br>f"{intent} task '{task.id}' has security critical_flow declarations without security-related verification checks" | `src/cccc/ralph/validation_rules/discipline_security.py:52`<br>`src/cccc/ralph/validation_rules/discipline_security.py:53` |
| `E_AGENT_REVIEW_FAILED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_CONSUMER_FROM_UNKNOWN` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' from unknown task '{c.from_task}'" | `src/cccc/ralph/validation_rules/contracts.py:55`<br>`src/cccc/ralph/validation_rules/contracts.py:56` |
| `E_CONSUMER_WITHOUT_PROVIDER` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' but no task provides it" | `src/cccc/ralph/validation_rules/contracts.py:45`<br>`src/cccc/ralph/validation_rules/contracts.py:46` |
| `E_COVERS_UNKNOWN_FLOW` | Source token reference.<br>f"task '{task.id}' covers flow '{flow_id}' which is not declared in critical_flows or forbidden_flows" | `src/cccc/ralph/validation_rules/coverage.py:1013`<br>`src/cccc/ralph/validation_rules/coverage.py:1014` |
| `E_COVERS_UNKNOWN_TASK` | Source token reference.<br>f"task '{task.id}' covers unknown task '{covered_id}'" | `src/cccc/ralph/validation_rules/structural.py:135`<br>`src/cccc/ralph/validation_rules/structural.py:136` |
| `E_COVERS_WITHOUT_DEP_ORDER` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but '{covered_id}' is not in its transitive dependency closure" | `src/cccc/ralph/validation_rules/structural.py:147`<br>`src/cccc/ralph/validation_rules/structural.py:148` |
| `E_CRITICAL_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:503`<br>`src/cccc/ralph/validation_rules/coverage.py:504` |
| `E_CRITICAL_FLOW_ENTRYPOINT_UNOWNED` | Source token reference.<br>message | `src/cccc/ralph/validation_rules/coverage.py:570`<br>`src/cccc/ralph/validation_rules/coverage.py:571` |
| `E_CRITICAL_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"critical flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:714`<br>`src/cccc/ralph/validation_rules/coverage.py:715` |
| `E_CRITICAL_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] critical flow '{flow.id}' is not covered by any task's verification"<br>f"[suppress_flows] critical flow '{flow.id}' is not covered by any task's verification"<br>f"critical flow '{flow.id}' is not covered by any task's verification" | `src/cccc/ralph/validation_rules/coverage.py:1160`<br>`src/cccc/ralph/validation_rules/coverage.py:522`<br>`src/cccc/ralph/validation_rules/coverage.py:523`<br>`src/cccc/ralph/validation_rules/coverage.py:533`<br>`src/cccc/ralph/validation_rules/coverage.py:534`<br>`src/cccc/ralph/validation_rules/coverage.py:544`<br>`src/cccc/ralph/validation_rules/coverage.py:545`<br>`src/cccc/ralph/validation_rules/coverage.py:709` |
| `E_CYCLE_DETECTED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `E_DEP_CYCLE` | Source token reference.<br>f"dependency cycle detected involving: {', '.join(cycle)}" | `src/cccc/ralph/validation_rules/structural.py:83`<br>`src/cccc/ralph/validation_rules/structural.py:84` |
| `E_DEP_SELF` | Source token reference.<br>f"task '{t.id}' depends on itself" | `src/cccc/ralph/validation_rules/structural.py:73`<br>`src/cccc/ralph/validation_rules/structural.py:74` |
| `E_DEP_UNKNOWN` | Source token reference.<br>f"task '{t.id}' depends on unknown task '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:62`<br>`src/cccc/ralph/validation_rules/structural.py:63` |
| `E_DUPLICATE_FLOW_ID` | Source token reference.<br>f"duplicate critical_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:1078`<br>`src/cccc/ralph/validation_rules/coverage.py:1079` |
| `E_DUPLICATE_FORBIDDEN_FLOW_ID` | Source token reference.<br>f"duplicate forbidden_flow id '{flow.id}'" | `src/cccc/ralph/validation_rules/coverage.py:1092`<br>`src/cccc/ralph/validation_rules/coverage.py:1093` |
| `E_DUPLICATE_INVARIANT_NAME` | Source token reference.<br>f"duplicate registration_invariant name '{inv.name}'" | `src/cccc/ralph/validation_rules/coverage.py:1106`<br>`src/cccc/ralph/validation_rules/coverage.py:1107` |
| `E_DUPLICATE_TASK_ID` | Source token reference.<br>f"duplicate task id '{t.id}'" | `src/cccc/ralph/validation_rules/structural.py:50`<br>`src/cccc/ralph/validation_rules/structural.py:51` |
| `E_FORBIDDEN_FLOW_LEVEL_TOO_WEAK` | Source token reference.<br>f"forbidden flow '{flow.id}' requires {flow.required_verification_level} but best coverage is {actual_name}" | `src/cccc/ralph/validation_rules/coverage.py:920`<br>`src/cccc/ralph/validation_rules/coverage.py:921` |
| `E_FORBIDDEN_FLOW_UNCOVERED` | Source token reference.<br>f"[deferred] forbidden flow '{flow.id}' has no negative test covering it"<br>f"forbidden flow '{flow.id}' has no negative test covering it" | `src/cccc/ralph/validation_rules/coverage.py:898`<br>`src/cccc/ralph/validation_rules/coverage.py:899`<br>`src/cccc/ralph/validation_rules/coverage.py:909`<br>`src/cccc/ralph/validation_rules/coverage.py:910` |
| `E_MISSING_CLAIMED_PATHS` | Source token reference.<br>f"task '{t.id}' has no claimed_paths" | `src/cccc/ralph/validation_rules/structural.py:167`<br>`src/cccc/ralph/validation_rules/structural.py:168` |
| `E_MISSING_INTEGRATION_SPINE` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no task provides integration/e2e verification covering multiple tasks' | `src/cccc/ralph/validation_rules/structural.py:473`<br>`src/cccc/ralph/validation_rules/structural.py:474` |
| `E_MISSING_VERIFICATION` | Source token reference.<br>f"task '{t.id}' has no verification defined" | `src/cccc/ralph/validation_rules/structural.py:175`<br>`src/cccc/ralph/validation_rules/structural.py:176` |
| `E_MOCK_TEST_MISSING_NAME` | Source token reference.<br>f"task '{t.id}' has a mock_test with empty name" | `src/cccc/ralph/validation_rules/coverage.py:849`<br>`src/cccc/ralph/validation_rules/coverage.py:850` |
| `E_MOCK_TEST_MISSING_VERIFY_COMMAND` | Source token reference.<br>f"task '{t.id}' mock_test '{mt.name}' has no verify_command" | `src/cccc/ralph/validation_rules/coverage.py:856`<br>`src/cccc/ralph/validation_rules/coverage.py:857` |
| `E_MODULE_DUPLICATE_ID` | Source token reference.<br>f"task '{task.id}' has duplicate module id '{mod.id}'" | `src/cccc/ralph/validation_rules/structural.py:662`<br>`src/cccc/ralph/validation_rules/structural.py:670`<br>`src/cccc/ralph/validation_rules/structural.py:671` |
| `E_MODULE_UNKNOWN_DEP` | Source token reference.<br>f"task '{task.id}' module '{mod.id}' depends on unknown module '{dep}'" | `src/cccc/ralph/validation_rules/structural.py:662`<br>`src/cccc/ralph/validation_rules/structural.py:681`<br>`src/cccc/ralph/validation_rules/structural.py:682` |
| `E_NO_CROSS_TASK_VERIFICATION` | Source token reference.<br>f'plan has {len(plan.tasks)} tasks but no integration/e2e verification covers multiple tasks' | `src/cccc/ralph/validation_rules/coverage.py:79`<br>`src/cccc/ralph/validation_rules/coverage.py:80` |
| `E_UNCOVERED_REQUIRED_ISSUE` | Source token reference.<br>f"required issue '{issue_id}' is not addressed by any task" | `src/cccc/ralph/validation_rules/coverage.py:1163`<br>`src/cccc/ralph/validation_rules/coverage.py:770`<br>`src/cccc/ralph/validation_rules/coverage.py:771` |
| `E_VERIFICATION_SHALLOW_CRITICAL` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:140` |
| `E_VERIFICATION_TARGET_MISSING_FILE` | Source token reference.<br>f"task '{task_id}' references missing file '{rel_path}'" | `src/cccc/ralph/filesystem_validator.py:988`<br>`src/cccc/ralph/filesystem_validator.py:989` |
| `E_WRITE_CONFLICT` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:24` |
| `H_DUPLICATE_ISSUE_ADDRESS` | Source token reference.<br>f"issue '{issue_id}' is addressed by multiple tasks: {', '.join(sorted(task_ids))}" | `src/cccc/ralph/validation_rules/coverage.py:817`<br>`src/cccc/ralph/validation_rules/coverage.py:818` |
| `H_MOCK_TESTS_ON_RALPH_MODE` | Source token reference.<br>f"task '{t.id}' has mock_tests but verification_mode='ralph'; mock_tests only run in agent/challenge mode" | `src/cccc/ralph/validation_rules/coverage.py:838`<br>`src/cccc/ralph/validation_rules/coverage.py:839` |
| `H_SUPPRESS_UNUSED` | Source token reference.<br>f"suppress_codes entry '{code}' did not match any emitted issue" | `src/cccc/ralph/validation_rules/coverage.py:1140`<br>`src/cccc/ralph/validation_rules/coverage.py:1141` |
| `H_VERIFICATION_COMMAND_DEAD` | Source token reference.<br>f"task '{task.id}' verification.command is ignored in favor of structured checks" | `src/cccc/ralph/validation_rules/coverage.py:186`<br>`src/cccc/ralph/validation_rules/coverage.py:187` |
| `W_AEGIS_COMPLEX_MISSING_BASELINE` | Source token reference.<br>f"complex task '{task.id}' has no aegis.baseline_refs" | `src/cccc/ralph/validation_rules/discipline.py:134`<br>`src/cccc/ralph/validation_rules/discipline.py:136` |
| `W_AEGIS_DECISION_HYGIENE_MISSING` | Source token reference.<br>f"task '{task.id}' introduces owner-pattern risk without decision_review" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:58`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:60` |
| `W_AEGIS_DRIFT_CHECK_MISSING` | Source token reference.<br>f"task '{task.id}' has {module_count} modules without aegis.drift_check" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:77`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:79` |
| `W_AEGIS_FIX_NO_REPAIR_TRACK` | Source token reference.<br>f"fix task '{task.id}' has no repair_track" | `src/cccc/ralph/validation_rules/discipline.py:96`<br>`src/cccc/ralph/validation_rules/discipline.py:98` |
| `W_AEGIS_PATCH_SHAPE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has patch-shape risk without aegis.patch_shape_triage" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:23`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:25` |
| `W_AEGIS_PLAN_NO_COMPAT_BOUNDARY` | Source token reference.<br>plan has cross-task dependencies but no task declares aegis.compat_boundary | `src/cccc/ralph/validation_rules/discipline_second_wave.py:92`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:93` |
| `W_AEGIS_RIPPLE_TRIAGE_MISSING` | Source token reference.<br>f"task '{task.id}' has ripple risk without downstream awareness_paths" | `src/cccc/ralph/validation_rules/discipline_second_wave.py:41`<br>`src/cccc/ralph/validation_rules/discipline_second_wave.py:43` |
| `W_AEGIS_TDD_NO_TEST_PATH` | Source token reference.<br>f"{intent} task '{task.id}' claims no test path" | `src/cccc/ralph/validation_rules/discipline.py:115`<br>`src/cccc/ralph/validation_rules/discipline.py:117` |
| `W_AGENT_REVIEW_SKIPPED` | Template reference not found in scanned rule sources. | `plans/_template.yaml:template` |
| `W_AUTH_TIMING_UNSAFE` | Source token reference. | `src/cccc/ralph/security_recipes.py:33` |
| `W_BATCH_E2E_NO_COMMAND` | Source token reference.<br>f"plan has {dep_layers} dependency layers but no batch_e2e_command — cross-task integration won't be verified between batches" | `src/cccc/ralph/validation_rules/coverage.py:1301`<br>`src/cccc/ralph/validation_rules/coverage.py:1311`<br>`src/cccc/ralph/validation_rules/coverage.py:1312` |
| `W_CLAIMED_PATH_INCOMPLETE` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:26` |
| `W_CONFTEST_COVERAGE_GAP` | Source token reference.<br>f"task '{task_id}' source '{source_path}' has {count} related conftest(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:233`<br>`src/cccc/ralph/filesystem_validator.py:234`<br>`src/cccc/ralph/filesystem_validator.py:440` |
| `W_CONSUME_WITHOUT_DEP` | Source token reference.<br>f"task '{t.id}' consumes from '{src}' but does not depend on it" | `src/cccc/ralph/validation_rules/contracts.py:160`<br>`src/cccc/ralph/validation_rules/contracts.py:161` |
| `W_CONTRACT_SCHEMA_MISMATCH` | Source token reference.<br>f"task '{t.id}' consumes '{c.name}' with an incompatible schema hint" | `src/cccc/ralph/validation_rules/contracts.py:66`<br>`src/cccc/ralph/validation_rules/contracts.py:67` |
| `W_CONTRACT_SIGNATURE_MISMATCH` | Source token reference.<br>f"task '{consumer_task_id}' consumes '{consumer.name}' with signature mismatch" | `src/cccc/ralph/validation_rules/contracts.py:229`<br>`src/cccc/ralph/validation_rules/contracts.py:230` |
| `W_COVERS_CLAIM_UNVERIFIABLE` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification command does not reference any claimed_paths of '{covered_id}'" | `src/cccc/ralph/validation_rules/coverage.py:431`<br>`src/cccc/ralph/validation_rules/coverage.py:432` |
| `W_COVERS_NOT_EXERCISED` | Source token reference.<br>f"task '{task.id}' covers '{covered_id}' but its verification does not reference the covered paths" | `src/cccc/ralph/validation_rules/coverage.py:210`<br>`src/cccc/ralph/validation_rules/coverage.py:211` |
| `W_CRITICAL_FLOW_NO_ENTRYPOINTS` | Source token reference.<br>f"critical flow '{flow.id}' has no entrypoints declared" | `src/cccc/ralph/validation_rules/coverage.py:1124`<br>`src/cccc/ralph/validation_rules/coverage.py:1125` |
| `W_CRITICAL_FLOW_WORKER_ONLY_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims critical flow entrypoints but uses verification_mode='{task.verification_mode}' instead of agent/challenge" | `src/cccc/ralph/validation_rules/coverage.py:737`<br>`src/cccc/ralph/validation_rules/coverage.py:738` |
| `W_CROSS_BOUNDARY_WITHOUT_GLUE` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' across different path boundaries, but no integration/e2e verification covers both" | `src/cccc/ralph/validation_rules/structural.py:451`<br>`src/cccc/ralph/validation_rules/structural.py:452` |
| `W_CROSS_TASK_IO_MISMATCH` | Source token reference.<br>f"task '{task.id}' expects input keys {sorted(missing)} not provided by any upstream dependency's expected_output" | `src/cccc/ralph/validation_rules/contracts.py:348`<br>`src/cccc/ralph/validation_rules/contracts.py:370`<br>`src/cccc/ralph/validation_rules/contracts.py:371` |
| `W_DEP_WITHOUT_CONSUME` | Source token reference.<br>f"task '{t.id}' depends on '{dep_id}' which provides contracts, but does not consume any of them" | `src/cccc/ralph/validation_rules/contracts.py:172`<br>`src/cccc/ralph/validation_rules/contracts.py:173` |
| `W_DISCONNECTED_COMPONENTS` | Source token reference.<br>f'plan has {len(components)} disconnected task groups' | `src/cccc/ralph/validation_rules/structural.py:94`<br>`src/cccc/ralph/validation_rules/structural.py:95` |
| `W_DYNAMIC_TEST_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' source '{source_path}' is dynamically imported by '{test_path}'" | `src/cccc/ralph/filesystem_validator.py:217`<br>`src/cccc/ralph/filesystem_validator.py:431`<br>`src/cccc/ralph/filesystem_validator.py:432` |
| `W_E2E_MISSING_COMPILE_CHECK` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:27` |
| `W_EMPTY_ACCEPTANCE` | Source token reference.<br>f"task '{t.id}' has no acceptance_criteria" | `src/cccc/ralph/validation_rules/structural.py:183`<br>`src/cccc/ralph/validation_rules/structural.py:184` |
| `W_FINDING_REF_INCOMPLETE` | Source token reference.<br>f"finding_ref '{ref.id}' is missing mitigation"<br>finding_ref is missing id | `src/cccc/ralph/validation_rules/coverage.py:941`<br>`src/cccc/ralph/validation_rules/coverage.py:942`<br>`src/cccc/ralph/validation_rules/coverage.py:948`<br>`src/cccc/ralph/validation_rules/coverage.py:949` |
| `W_FINDING_REF_UNKNOWN_ENFORCER` | Source token reference.<br>f"finding_ref '{ref.id}' references unknown enforcer '{enforcer}'" | `src/cccc/ralph/validation_rules/coverage.py:957`<br>`src/cccc/ralph/validation_rules/coverage.py:958` |
| `W_FLOW_OWNER_NO_VERIFICATION` | Source token reference.<br>f"task '{task.id}' claims entrypoint '{entrypoint}' of flow '{flow.id}' but doesn't verify the flow" | `src/cccc/ralph/validation_rules/coverage.py:677`<br>`src/cccc/ralph/validation_rules/coverage.py:678` |
| `W_FLOW_SEGMENT_UNOWNED` | Source token reference.<br>f"task '{task.id}' covers flow '{flow.id}' but doesn't claim any of its entrypoints" | `src/cccc/ralph/validation_rules/coverage.py:660`<br>`src/cccc/ralph/validation_rules/coverage.py:661` |
| `W_GLOBAL_WRITE_CLAIM` | Source token reference.<br>f"task '{t.id}' claims global write ('/') — blocks all parallel tasks" | `src/cccc/ralph/validation_rules/structural.py:204`<br>`src/cccc/ralph/validation_rules/structural.py:205` |
| `W_INDIRECT_TEST_IMPORT` | Source token reference.<br>f"task '{task_id}' has {len(entries)} indirect test import hint(s) not covered by any verification; showing first {len(samples)} sample(s)"<br>f"task '{task_id}' source '{source_path}' has {count} related test(s) not covered by any verification" | `src/cccc/ralph/filesystem_validator.py:476`<br>`src/cccc/ralph/filesystem_validator.py:477`<br>`src/cccc/ralph/filesystem_validator.py:493`<br>`src/cccc/ralph/filesystem_validator.py:494` |
| `W_INTEGRATION_INTERFACE_MISMATCH` | Source token reference.<br>f"task '{task.id}' consumes '{contract.name}' from '{contract.from_task}' but verification does not reference any of {contract.from_task}'s paths" | `src/cccc/ralph/validation_rules/contracts.py:124`<br>`src/cccc/ralph/validation_rules/contracts.py:125` |
| `W_INTEGRATION_ROLE_WEAK_VERIFICATION` | Source token reference.<br>f"task '{task.id}' has role='integration' but lacks integration/e2e verification covering at least 2 tasks" | `src/cccc/ralph/validation_rules/structural.py:493`<br>`src/cccc/ralph/validation_rules/structural.py:494` |
| `W_INTEGRATION_TASK_SHALLOW_VERIFICATION` | Source token reference.<br>f"task '{task.id}' integration verification is shallow and lacks a behavioral check" | `src/cccc/ralph/validation_rules/coverage.py:168`<br>`src/cccc/ralph/validation_rules/coverage.py:169` |
| `W_ISOLATED_TASK` | Source token reference.<br>f"task '{t.id}' has no dependency edges (neither depends on others nor depended upon)" | `src/cccc/ralph/validation_rules/structural.py:110`<br>`src/cccc/ralph/validation_rules/structural.py:111` |
| `W_LEAF_ROLE_IS_INTEGRATOR` | Source token reference.<br>f"task '{task.id}' has role='leaf' but provides integration/e2e verification covering multiple tasks" | `src/cccc/ralph/validation_rules/structural.py:533`<br>`src/cccc/ralph/validation_rules/structural.py:534` |
| `W_NO_EARLY_INTEGRATION_CHECKPOINT` | Source token reference.<br>all cross-task integration/e2e verifiers are sink tasks and appear late in the graph | `src/cccc/ralph/validation_rules/structural.py:573`<br>`src/cccc/ralph/validation_rules/structural.py:574` |
| `W_NO_FAILURE_PATH` | Source token reference.<br>f"task '{t.id}' involves assignment/actor operations but has no failure handling description or failure_path field" | `src/cccc/ralph/validation_rules/coverage.py:269`<br>`src/cccc/ralph/validation_rules/coverage.py:270` |
| `W_PLAN_SCOPE_UNUSED` | Source token reference.<br>f"registration invariant '{inv.name}' references '{inv.registry_file}' which is not claimed by any task" | `src/cccc/ralph/validation_rules/coverage.py:1178`<br>`src/cccc/ralph/validation_rules/coverage.py:1179` |
| `W_PROVIDER_UNUSED` | Source token reference.<br>f"contract '{name}' is provided but never consumed" | `src/cccc/ralph/validation_rules/contracts.py:92`<br>`src/cccc/ralph/validation_rules/contracts.py:93` |
| `W_REGISTRATION_INVARIANT_UNCOVERED` | Source token reference.<br>f"registration invariant '{inv.name}' registry file '{inv.registry_file}' is not claimed by any task" | `src/cccc/ralph/filesystem_validator.py:312`<br>`src/cccc/ralph/filesystem_validator.py:313` |
| `W_SHARED_FILE_PARTIAL_VERIFICATION` | Source token reference.<br>f"tasks '{t1.id}' and '{t2.id}' share paths but neither verification mentions them" | `src/cccc/ralph/validation_rules/structural.py:402`<br>`src/cccc/ralph/validation_rules/structural.py:403` |
| `W_SHARED_PATH_NO_DEPENDENCY` | Source token reference. | `src/cccc/ralph/validation_rules/structural.py:25` |
| `W_SSRF_ENCODING_UNCOVERED` | Source token reference. | `src/cccc/ralph/security_recipes.py:12` |
| `W_STATE_UNKNOWN_TASK_REF` | Source token reference.<br>f"state.completed_task_ids references unknown task '{tid}'"<br>f"state.failed_task_ids references unknown task '{tid}'"<br>f"state.running_tasks references unknown task '{rt.task_id}'" | `src/cccc/ralph/validation_rules/coverage.py:1033`<br>`src/cccc/ralph/validation_rules/coverage.py:1034`<br>`src/cccc/ralph/validation_rules/coverage.py:1045`<br>`src/cccc/ralph/validation_rules/coverage.py:1046`<br>`src/cccc/ralph/validation_rules/coverage.py:1057`<br>`src/cccc/ralph/validation_rules/coverage.py:1058` |
| `W_SUPPRESS_FLOWS_UNKNOWN` | Source token reference.<br>f"suppress_flows references unknown flow '{flow_id}'" | `src/cccc/ralph/validation_rules/coverage.py:973`<br>`src/cccc/ralph/validation_rules/coverage.py:974` |
| `W_TASK_ADDRESSES_DISJOINT` | Source token reference.<br>f"task '{t.id}' addresses issues from different domains: {', '.join(sorted(prefixes))}" | `src/cccc/ralph/validation_rules/coverage.py:799`<br>`src/cccc/ralph/validation_rules/coverage.py:800` |
| `W_TEST_COVERAGE_GAP` | Source code assignment literal.<br>Source token reference. | `src/cccc/ralph/filesystem_validator.py:242`<br>`src/cccc/ralph/filesystem_validator.py:440` |
| `W_UNCLAIMED_TEST_FOR_SOURCE` | Source token reference.<br>f"task '{task.id}' source '{source_path}' has related test '{test_path}' claimed by no task" | `src/cccc/ralph/filesystem_validator.py:355`<br>`src/cccc/ralph/filesystem_validator.py:356` |
| `W_UNKNOWN_VERIFICATION_MODE` | Source token reference.<br>f"task '{t.id}' has unknown verification_mode '{t.verification_mode}'" | `src/cccc/ralph/validation_rules/structural.py:193`<br>`src/cccc/ralph/validation_rules/structural.py:194` |
| `W_VERIFICATION_BEHAVIOR_MISMATCH` | Source token reference.<br>f"task '{t.id}' goal implies runtime behavior but verification is only {v.level}-level" | `src/cccc/ralph/validation_rules/coverage.py:324`<br>`src/cccc/ralph/validation_rules/coverage.py:325` |
| `W_VERIFICATION_COMPLEX_SHELL_SKIPPED` | Source token reference.<br>f"task '{task_id}' verification contains shell operators and was skipped" | `src/cccc/ralph/filesystem_validator.py:597`<br>`src/cccc/ralph/filesystem_validator.py:598` |
| `W_VERIFICATION_CROSS_SCOPE` | Source token reference.<br>f"task '{task.id}' verification check '{check.name}' references path '{ref_path}' which belongs to task '{other_id}'"<br>f"task '{task.id}' verification command references path '{ref_path}' which belongs to task '{other_id}'" | `src/cccc/ralph/validation_rules/coverage.py:365`<br>`src/cccc/ralph/validation_rules/coverage.py:366`<br>`src/cccc/ralph/validation_rules/coverage.py:391`<br>`src/cccc/ralph/validation_rules/coverage.py:392` |
| `W_VERIFICATION_DUPLICATE_COMMAND` | Source token reference.<br>f'tasks {task_ids} share the same verification command' | `src/cccc/ralph/validation_rules/coverage.py:297`<br>`src/cccc/ralph/validation_rules/coverage.py:298` |
| `W_VERIFICATION_IMPORT_MODULE_MISSING` | Source token reference.<br>f"task '{task_id}' imports module '{module_name}' which only the task itself claims (self-verification)"<br>message | `src/cccc/ralph/filesystem_validator.py:1015`<br>`src/cccc/ralph/filesystem_validator.py:1016`<br>`src/cccc/ralph/filesystem_validator.py:1031`<br>`src/cccc/ralph/filesystem_validator.py:1032` |
| `W_VERIFICATION_IMPORT_SYMBOL_MISSING` | Source token reference.<br>f"task '{task_id}' imports missing symbol '{alias.name}' from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:817`<br>`src/cccc/ralph/filesystem_validator.py:818` |
| `W_VERIFICATION_NO_CHECKS` | Source token reference.<br>f"task '{t.id}' has a verification command but no structured checks — consider splitting into at least a compile check and a behavior test check" | `src/cccc/ralph/validation_rules/coverage.py:109`<br>`src/cccc/ralph/validation_rules/coverage.py:110` |
| `W_VERIFICATION_PYTEST_K_NO_MATCH` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:929`<br>`src/cccc/ralph/filesystem_validator.py:930` |
| `W_VERIFICATION_PYTEST_NODE_MISSING` | Source token reference.<br>f"task '{task_id}' pytest target node '{node_part}' was not found in '{file_path}'" | `src/cccc/ralph/filesystem_validator.py:886`<br>`src/cccc/ralph/filesystem_validator.py:887` |
| `W_VERIFICATION_PYTHON_IMPORT_OPAQUE` | Source token reference.<br>f"task '{task_id}' import target '{module_name}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet is opaque to static import checks"<br>f"task '{task_id}' python -c uses relative or opaque imports"<br>f"task '{task_id}' uses wildcard import from '{module_name}'" | `src/cccc/ralph/filesystem_validator.py:744`<br>`src/cccc/ralph/filesystem_validator.py:745`<br>`src/cccc/ralph/filesystem_validator.py:768`<br>`src/cccc/ralph/filesystem_validator.py:769`<br>`src/cccc/ralph/filesystem_validator.py:796`<br>`src/cccc/ralph/filesystem_validator.py:797`<br>`src/cccc/ralph/filesystem_validator.py:807`<br>`src/cccc/ralph/filesystem_validator.py:808` |
| `W_VERIFICATION_PYTHON_SNIPPET_INVALID` | Source token reference.<br>f"task '{task_id}' python -c snippet is not valid Python" | `src/cccc/ralph/filesystem_validator.py:733`<br>`src/cccc/ralph/filesystem_validator.py:734` |
| `W_VERIFICATION_REDUNDANT_PYCOMPILE` | Source token reference.<br>f"task '{task_id}' verification uses redundant py_compile on '{target}'" | `src/cccc/ralph/filesystem_validator.py:703`<br>`src/cccc/ralph/filesystem_validator.py:704` |
| `W_VERIFICATION_ROLE_CLAIMS_SOURCE` | Source token reference.<br>f"task '{task.id}' has role='verification' but claims source path '{offending_path}'" | `src/cccc/ralph/validation_rules/structural.py:523`<br>`src/cccc/ralph/validation_rules/structural.py:524` |
| `W_VERIFICATION_ROLE_NO_COVERS` | Source token reference.<br>f"task '{task.id}' has role='verification' but no verification covers.tasks" | `src/cccc/ralph/validation_rules/structural.py:508`<br>`src/cccc/ralph/validation_rules/structural.py:509` |
| `W_VERIFICATION_SHALLOW_CHECKS` | Source token reference. | `src/cccc/ralph/validation_rules/coverage.py:142` |
| `W_VERIFICATION_SHAPE_UNKNOWN` | Source token reference.<br>f"task '{task_id}' pytest command has no static target"<br>f"task '{task_id}' pytest target '{file_path}' could not be parsed statically"<br>f"task '{task_id}' pytest target '{target}' could not be parsed statically"<br>f"task '{task_id}' python -c snippet shape not recognized"<br>f"task '{task_id}' verification command could not be parsed"<br>f"task '{task_id}' verification command empty after unwrap"<br>f"task '{task_id}' verification shape not recognized for static precheck" | `src/cccc/ralph/filesystem_validator.py:607`<br>`src/cccc/ralph/filesystem_validator.py:608`<br>`src/cccc/ralph/filesystem_validator.py:619`<br>`src/cccc/ralph/filesystem_validator.py:620`<br>`src/cccc/ralph/filesystem_validator.py:645`<br>`src/cccc/ralph/filesystem_validator.py:646`<br>`src/cccc/ralph/filesystem_validator.py:751`<br>`src/cccc/ralph/filesystem_validator.py:752`<br>`src/cccc/ralph/filesystem_validator.py:846`<br>`src/cccc/ralph/filesystem_validator.py:847`<br>`src/cccc/ralph/filesystem_validator.py:877`<br>`src/cccc/ralph/filesystem_validator.py:878`<br>`src/cccc/ralph/filesystem_validator.py:909`<br>`src/cccc/ralph/filesystem_validator.py:910` |
| `W_VERIFICATION_TARGET_MISSING` | Source token reference.<br>message | `src/cccc/ralph/filesystem_validator.py:970`<br>`src/cccc/ralph/filesystem_validator.py:971` |
| `W_VERIFICATION_TOCTOU_GAP` | Source token reference. | `src/cccc/ralph/security_recipes.py:51` |
| `W_VERIFICATION_TRIVIAL_COMMAND` | Source token reference.<br>f"task '{task_id}' verification is trivial command '{base}'" | `src/cccc/ralph/filesystem_validator.py:628`<br>`src/cccc/ralph/filesystem_validator.py:629` |
| `W_WEAK_VERIFICATION_ONLY` | Source token reference.<br>all verifications are compile-level only — no behavioral testing | `src/cccc/ralph/validation_rules/coverage.py:93`<br>`src/cccc/ralph/validation_rules/coverage.py:94` |
## CLI Commands Reference

| Command | Help | Arguments |
| --- | --- | --- |
| `validate` | Check plan for structural issues | `plan`, `--format`, `--project-root`, `--diff`, `--suppress`, `--gate`, `--no-semantic`, `--no-agent`, `--compact`, `--show-schema`, `--ledger`, `--group`, `--generate-security-checks` |
| `suggest` | Show next ready batch | `plan`, `--format` |
| `verify` | Run verification for a task | `plan`, `--task`, `--changed-files`, `--project-root` |
| `complete` | Mark a task as completed | `plan`, `--task`, `--verify`, `--project-root` |
| `explain` | Explain a task or a validation rule code | `plan`, `--task`, `--code` |
| `audit` | Audit ledger for operational issues | `--ledger`, `--format`, `--days` |
| `sync-state` | Sync completed tasks from ledger to plan | `plan`, `--ledger`, `--group` |
| `guide` | Auto-generate capability guide from plan schema and validation rules | `--output`, `--update`, `--since` |
| `flow` | Progressive workflow guidance |  |
| `start` | Start a new workflow | `flow_type`, `--workspace`, `--test-cmd`, `--tracker`, `--guide-output`, `--cccc-root`, `--version`, `--report-path` |
| `next` | Advance to next step | `--workspace` |
| `status` | Show current flow status | `--workspace` |
