def complete_workflow() -> None:
    engine.emit_workflow_terminal("wf-1")
    if workflow_evaluation_empty_sections("project"):
        return
