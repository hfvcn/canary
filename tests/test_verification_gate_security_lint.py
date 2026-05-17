from __future__ import annotations

from pathlib import Path
from typing import Any

from cccc.daemon.foreman.verification_gate import _check_security_lint


class _Engine:
    def __init__(self, *, raise_on_warning: bool = False) -> None:
        self.raise_on_warning = raise_on_warning
        self.warnings: list[dict[str, Any]] = []

    def record_verification_warning(self, task_id: str, **kwargs: Any) -> None:
        if self.raise_on_warning:
            raise RuntimeError("record failed")
        self.warnings.append({"task_id": task_id, **kwargs})


def test_security_lint_warns_on_debug_true_in_non_test_file(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("app.run(debug=True)\n", encoding="utf-8")
    engine = _Engine()

    _check_security_lint(engine, "T1", ["src/app.py"], tmp_path)

    assert len(engine.warnings) == 1
    warning = engine.warnings[0]
    assert warning["warning_type"] == "security_lint"
    assert warning["evidence"]["hits"][0]["type"] == "debug_true"


def test_security_lint_skips_debug_true_in_tests_path(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("app.run(debug=True)\n", encoding="utf-8")
    engine = _Engine()

    _check_security_lint(engine, "T1", ["tests/app.py"], tmp_path)

    assert engine.warnings == []


def test_security_lint_warns_on_fts_match_raw_input(tmp_path: Path) -> None:
    target = tmp_path / "src" / "search.py"
    target.parent.mkdir(parents=True)
    target.write_text('sql = "SELECT * FROM docs WHERE body MATCH ? " + user_input\n', encoding="utf-8")
    engine = _Engine()

    _check_security_lint(engine, "T1", ["src/search.py"], tmp_path)

    assert len(engine.warnings) == 1
    hit = engine.warnings[0]["evidence"]["hits"][0]
    assert hit["type"] == "fts_raw_input"


def test_security_lint_ignores_empty_changed_files(tmp_path: Path) -> None:
    engine = _Engine()

    _check_security_lint(engine, "T1", [], tmp_path)

    assert engine.warnings == []


def test_security_lint_swallows_record_warning_errors(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("app.run(debug=True)\n", encoding="utf-8")
    engine = _Engine(raise_on_warning=True)

    _check_security_lint(engine, "T1", ["src/app.py"], tmp_path)

    assert engine.warnings == []


def test_security_lint_skips_non_python_changed_files(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("app.run(debug=True)\n", encoding="utf-8")
    engine = _Engine()

    _check_security_lint(engine, "T1", ["README.md"], tmp_path)

    assert engine.warnings == []
