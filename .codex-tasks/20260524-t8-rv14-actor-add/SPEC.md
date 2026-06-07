# T8 RV-14 actor_add 返回值四层传播

## Goal

实现 `ActorAddResult` 在 `assignment_actor_registration -> assignment_controller -> workflow_orchestrator -> assignment_startup` 四层传播，保留 `running` 与 `start_error` 信息，并补齐对应测试。

## Scope

- `src/cccc/daemon/foreman/assignment_actor_registration.py`
- `src/cccc/daemon/foreman/assignment_controller.py`
- `src/cccc/daemon/foreman/workflow_orchestrator.py`
- `src/cccc/daemon/foreman/assignment_startup.py`
- `tests/test_assignment_startup.py`
- `tests/test_foreman_workflow.py`

## Validation

`python -m pytest tests/test_assignment_startup.py tests/test_foreman_workflow.py -v`
