from app.workflow_evaluation_check import describe_workflow_evaluation


def test_workflow_evaluation_fixture() -> None:
    assert "workflow evaluation" in describe_workflow_evaluation()
