"""Tests for task context persistence."""

from __future__ import annotations

from pathlib import Path

from cccc.daemon.foreman.context_store import ContextStore, TaskContext


def test_save_load_roundtrip(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    context = TaskContext(
        goal="恢复任务上下文",
        completed_steps=["分析日志", "定位失败点"],
        unresolved=["需要确认输入来源"],
        next_steps=["补充验证用例"],
        last_error="previous failure",
        changed_files=["src/demo.py", "tests/test_demo.py"],
    )

    path = store.save("T5", context)
    loaded = store.load("T5")

    assert path == tmp_path / ".cccc" / "task_contexts" / "T5.yaml"
    assert loaded is not None
    assert loaded.goal == context.goal
    assert loaded.completed_steps == context.completed_steps
    assert loaded.unresolved == context.unresolved
    assert loaded.next_steps == context.next_steps
    assert loaded.last_error == context.last_error
    assert loaded.changed_files == context.changed_files
    assert loaded.iteration == 1
    assert loaded.updated_at


def test_load_nonexistent_returns_none(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)

    assert store.load("missing-task") is None


def test_render_prompt_section() -> None:
    context = TaskContext(
        goal="完成 E-3",
        completed_steps=["创建模块"],
        unresolved=["补测试"],
        next_steps=["运行 pytest"],
        iteration=2,
        last_error="assertion failed",
        changed_files=["src/cccc/daemon/foreman/context_store.py"],
    )

    rendered = ContextStore.render_prompt_section(context)

    assert "第 2 次尝试" in rendered
    assert "**目标**: 完成 E-3" in rendered
    assert "**已完成**:" in rendered
    assert "- 创建模块" in rendered
    assert "**未解决**:" in rendered
    assert "- 补测试" in rendered
    assert "**上次错误**: assertion failed" in rendered
    assert "**建议下一步**:" in rendered
    assert "- 运行 pytest" in rendered
    assert "**已变更文件**: src/cccc/daemon/foreman/context_store.py" in rendered


def test_iteration_auto_increment(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)

    store.save("T5", TaskContext(goal="first"))
    first = store.load("T5")
    store.save("T5", TaskContext(goal="second"))
    second = store.load("T5")

    assert first is not None
    assert second is not None
    assert first.iteration == 1
    assert second.iteration == 2


def test_directory_auto_create(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)

    assert not store.context_dir.exists()
    store.save("T5", TaskContext(goal="create dir"))

    assert store.context_dir.is_dir()


def test_save_with_changed_files(tmp_path: Path) -> None:
    store = ContextStore(tmp_path)
    changed_files = ["src/one.py", "src/two.py"]

    store.save("T5", TaskContext(changed_files=changed_files))
    loaded = store.load("T5")

    assert loaded is not None
    assert loaded.changed_files == changed_files


def test_render_empty_context() -> None:
    rendered = ContextStore.render_prompt_section(TaskContext())

    assert "## 上次执行记录（第 0 次尝试）" in rendered
