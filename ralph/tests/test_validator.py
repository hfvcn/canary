"""
Tests for the Validator module.

Tests build/test validation, task state checking, and feedback generation.
"""

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from ralph.validator import (
    ValidatorConfig,
    CommandConfig,
    BuildTestValidator,
    BuildTestResult,
    TaskStateChecker,
    TaskStateResult,
    TaskState,
    FeedbackGenerator,
    run_build,
    run_tests,
    run_lint,
    check_task_state,
    generate_retry_message,
    generate_escalation_message,
)
from ralph.validator.build_test import ValidationStatus, CommandResult


class TestCommandConfig:
    """CommandConfig 测试"""

    def test_create_command_config(self):
        """测试创建命令配置"""
        config = CommandConfig(
            command="pytest",
            timeout=60.0,
            working_dir="tests",
        )
        assert config.command == "pytest"
        assert config.timeout == 60.0
        assert config.working_dir == "tests"
        assert config.required is True

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "command": "npm test",
            "timeout": 120.0,
            "required": False,
        }
        config = CommandConfig.from_dict(data)
        assert config.command == "npm test"
        assert config.timeout == 120.0
        assert config.required is False

    def test_to_dict(self):
        """测试转换为字典"""
        config = CommandConfig(command="make build", timeout=300.0)
        data = config.to_dict()
        assert data["command"] == "make build"
        assert data["timeout"] == 300.0


class TestValidatorConfig:
    """ValidatorConfig 测试"""

    def test_create_config(self):
        """测试创建配置"""
        config = ValidatorConfig(
            project_root=Path("/tmp/project"),
            build_command=CommandConfig(command="make"),
            max_retries=5,
        )
        assert config.project_root == Path("/tmp/project")
        assert config.build_command.command == "make"
        assert config.max_retries == 5

    def test_cccc_path(self):
        """测试 .cccc 路径"""
        config = ValidatorConfig(project_root=Path("/tmp/project"))
        assert config.cccc_path == Path("/tmp/project/.cccc")
        assert config.actors_path == Path("/tmp/project/.cccc/actors")

    def test_default_for_python(self):
        """测试 Python 项目默认配置"""
        config = ValidatorConfig.default_for_python(Path("/tmp/project"))
        assert config.test_command is not None
        assert "pytest" in config.test_command.command

    def test_default_for_node(self):
        """测试 Node.js 项目默认配置"""
        config = ValidatorConfig.default_for_node(Path("/tmp/project"))
        assert config.build_command is not None
        assert "npm" in config.build_command.command


class TestCommandResult:
    """CommandResult 测试"""

    def test_passed_result(self):
        """测试通过的结果"""
        result = CommandResult(
            command="echo hello",
            status=ValidationStatus.PASS,
            exit_code=0,
            stdout="hello\n",
        )
        assert result.passed is True

    def test_failed_result(self):
        """测试失败的结果"""
        result = CommandResult(
            command="exit 1",
            status=ValidationStatus.FAIL,
            exit_code=1,
        )
        assert result.passed is False

    def test_to_dict(self):
        """测试转换为字典"""
        result = CommandResult(
            command="test",
            status=ValidationStatus.PASS,
            exit_code=0,
            duration=1.5,
        )
        data = result.to_dict()
        assert data["status"] == "pass"
        assert data["exit_code"] == 0


class TestBuildTestResult:
    """BuildTestResult 测试"""

    def test_overall_passed_all_pass(self):
        """测试全部通过"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.PASS, exit_code=0
            ),
            test_result=CommandResult(
                command="test", status=ValidationStatus.PASS, exit_code=0
            ),
        )
        assert result.overall_passed is True
        assert result.build_passed is True
        assert result.test_passed is True

    def test_overall_passed_build_fail(self):
        """测试构建失败"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.FAIL, exit_code=1
            ),
        )
        assert result.overall_passed is False
        assert result.build_passed is False

    def test_overall_passed_lint_fail_ok(self):
        """测试 Lint 失败不影响整体"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.PASS, exit_code=0
            ),
            test_result=CommandResult(
                command="test", status=ValidationStatus.PASS, exit_code=0
            ),
            lint_result=CommandResult(
                command="lint", status=ValidationStatus.FAIL, exit_code=1
            ),
        )
        # Lint 失败不影响 overall_passed（因为 overall_passed 只检查 build 和 test）
        assert result.overall_passed is True
        assert result.lint_passed is False

    def test_skip_status(self):
        """测试跳过状态"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="", status=ValidationStatus.SKIP
            ),
        )
        assert result.overall_passed is True  # SKIP 视为通过


class TestRunCommands:
    """命令执行测试"""

    @pytest.fixture
    def temp_project(self):
        """创建临时项目目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_run_build_success(self, temp_project):
        """测试成功执行构建"""
        config = ValidatorConfig(
            project_root=temp_project,
            build_command=CommandConfig(
                command="echo 'build success'",
                timeout=10.0,
            ),
        )
        result = await run_build(config)
        assert result.passed is True
        assert "build success" in result.stdout

    @pytest.mark.asyncio
    async def test_run_build_failure(self, temp_project):
        """测试构建失败"""
        config = ValidatorConfig(
            project_root=temp_project,
            build_command=CommandConfig(
                command="exit 1",
                timeout=10.0,
            ),
        )
        result = await run_build(config)
        assert result.passed is False
        assert result.exit_code == 1

    @pytest.mark.asyncio
    async def test_run_build_skip(self, temp_project):
        """测试跳过构建（未配置）"""
        config = ValidatorConfig(project_root=temp_project)
        result = await run_build(config)
        assert result.status == ValidationStatus.SKIP

    @pytest.mark.asyncio
    async def test_run_tests_success(self, temp_project):
        """测试成功执行测试"""
        config = ValidatorConfig(
            project_root=temp_project,
            test_command=CommandConfig(
                command="echo 'all tests passed'",
                timeout=10.0,
            ),
        )
        result = await run_tests(config)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_run_lint_success(self, temp_project):
        """测试成功执行 lint"""
        config = ValidatorConfig(
            project_root=temp_project,
            lint_command=CommandConfig(
                command="echo 'no lint errors'",
                timeout=10.0,
            ),
        )
        result = await run_lint(config)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_run_command_timeout(self, temp_project):
        """测试命令超时"""
        config = ValidatorConfig(
            project_root=temp_project,
            build_command=CommandConfig(
                command="sleep 10",
                timeout=0.1,  # 100ms 超时
            ),
        )
        result = await run_build(config)
        assert result.status == ValidationStatus.TIMEOUT


class TestBuildTestValidator:
    """BuildTestValidator 测试"""

    @pytest.fixture
    def temp_project(self):
        """创建临时项目目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.mark.asyncio
    async def test_validate_all_pass(self, temp_project):
        """测试全部验证通过"""
        config = ValidatorConfig(
            project_root=temp_project,
            build_command=CommandConfig(command="echo build", timeout=10.0),
            test_command=CommandConfig(command="echo test", timeout=10.0),
            lint_command=CommandConfig(command="echo lint", timeout=10.0),
        )
        validator = BuildTestValidator(config)
        result = await validator.validate(
            task_id="TASK-001",
            commit_hash="abc123",
        )
        assert result.overall_passed is True

    @pytest.mark.asyncio
    async def test_validate_partial_fail(self, temp_project):
        """测试部分验证失败"""
        config = ValidatorConfig(
            project_root=temp_project,
            build_command=CommandConfig(command="echo build", timeout=10.0),
            test_command=CommandConfig(command="exit 1", timeout=10.0),
        )
        validator = BuildTestValidator(config)
        result = await validator.validate(
            task_id="TASK-001",
            commit_hash="abc123",
        )
        assert result.overall_passed is False
        assert result.build_passed is True
        assert result.test_passed is False


class TestTaskStateChecker:
    """TaskStateChecker 测试"""

    @pytest.fixture
    def temp_project_with_actors(self):
        """创建带 actors 目录的临时项目"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            actors_dir = project_root / ".cccc" / "actors" / "worker-1"
            actors_dir.mkdir(parents=True)

            # 创建 state.json
            state_data = {
                "current_task": "TASK-001",
                "status": "active",
                "next_action": "continue",
                "iteration": 1,
                "last_commit": "abc123",
                "updated_at": datetime.now().isoformat(),
            }
            state_file = actors_dir / "state.json"
            state_file.write_text(json.dumps(state_data))

            yield project_root

    def test_check_task_state_valid(self, temp_project_with_actors):
        """测试检查有效的任务状态"""
        config = ValidatorConfig(project_root=temp_project_with_actors)
        result = check_task_state(
            config=config,
            actor_id="worker-1",
            task_id="TASK-001",
        )
        assert result.is_valid is True
        assert result.state is not None
        assert result.state.status == TaskState.ACTIVE

    def test_check_task_state_task_id_mismatch(self, temp_project_with_actors):
        """测试任务 ID 不匹配"""
        config = ValidatorConfig(project_root=temp_project_with_actors)
        result = check_task_state(
            config=config,
            actor_id="worker-1",
            task_id="TASK-002",  # 不匹配
        )
        assert result.is_valid is False
        assert any("mismatch" in issue.lower() for issue in result.issues)

    def test_check_task_state_file_not_found(self, temp_project_with_actors):
        """测试状态文件不存在"""
        config = ValidatorConfig(project_root=temp_project_with_actors)
        result = check_task_state(
            config=config,
            actor_id="nonexistent-actor",
            task_id="TASK-001",
        )
        assert result.is_valid is False
        assert any("not found" in issue.lower() for issue in result.issues)

    def test_list_actors(self, temp_project_with_actors):
        """测试列出 Actor"""
        config = ValidatorConfig(project_root=temp_project_with_actors)
        checker = TaskStateChecker(config)
        actors = checker.list_actors()
        assert "worker-1" in actors

    def test_get_all_states(self, temp_project_with_actors):
        """测试获取所有状态"""
        config = ValidatorConfig(project_root=temp_project_with_actors)
        checker = TaskStateChecker(config)
        states = checker.get_all_states()
        assert "worker-1" in states
        assert states["worker-1"].current_task == "TASK-001"


class TestFeedbackGenerator:
    """FeedbackGenerator 测试"""

    def test_generate_success(self):
        """测试生成成功消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.PASS, exit_code=0
            ),
        )
        generator = FeedbackGenerator()
        feedback = generator.generate(build_test_result=result)
        assert feedback.type.value == "success"

    def test_generate_retry(self):
        """测试生成重试消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.FAIL, exit_code=1
            ),
        )
        generator = FeedbackGenerator(max_retries=3)
        feedback = generator.generate(build_test_result=result)
        assert feedback.type.value == "retry"
        assert feedback.can_retry is True

    def test_generate_escalation(self):
        """测试生成升级消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.FAIL, exit_code=1
            ),
        )
        generator = FeedbackGenerator(max_retries=2)

        # 模拟多次失败
        generator.generate(build_test_result=result)
        generator.generate(build_test_result=result)
        feedback = generator.generate(build_test_result=result)

        assert feedback.type.value == "escalation"
        assert feedback.can_retry is False

    def test_reset_retry_count(self):
        """测试重置重试计数"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build", status=ValidationStatus.FAIL, exit_code=1
            ),
        )
        generator = FeedbackGenerator()
        generator.generate(build_test_result=result)
        assert generator.get_retry_count("TASK-001") == 1

        generator.reset("TASK-001")
        assert generator.get_retry_count("TASK-001") == 0


class TestGenerateRetryMessage:
    """generate_retry_message 测试"""

    def test_build_failure(self):
        """测试构建失败消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="make build",
                status=ValidationStatus.FAIL,
                exit_code=1,
                stderr="error: undefined reference",
            ),
        )
        feedback = generate_retry_message(build_test_result=result)
        assert "构建失败" in feedback.title or "构建" in str(feedback.suggestions)

    def test_test_failure(self):
        """测试测试失败消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            test_result=CommandResult(
                command="pytest",
                status=ValidationStatus.FAIL,
                exit_code=1,
                stderr="AssertionError: expected 1, got 2",
            ),
        )
        feedback = generate_retry_message(build_test_result=result)
        assert "测试失败" in feedback.title or "断言" in str(feedback.suggestions)

    def test_timeout_failure(self):
        """测试超时失败消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            test_result=CommandResult(
                command="pytest",
                status=ValidationStatus.TIMEOUT,
                duration=300.0,
            ),
        )
        feedback = generate_retry_message(build_test_result=result)
        assert "超时" in feedback.details or "timeout" in feedback.details.lower()


class TestGenerateEscalationMessage:
    """generate_escalation_message 测试"""

    def test_escalation_message(self):
        """测试升级消息"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build",
                status=ValidationStatus.FAIL,
                exit_code=1,
            ),
        )
        feedback = generate_escalation_message(
            build_test_result=result,
            retry_count=3,
            reason="多次重试失败",
        )
        assert feedback.type.value == "escalation"
        assert "人工" in feedback.title or "介入" in feedback.title

    def test_escalation_to_markdown(self):
        """测试升级消息转 Markdown"""
        result = BuildTestResult(
            task_id="TASK-001",
            commit_hash="abc123",
            build_result=CommandResult(
                command="build",
                status=ValidationStatus.FAIL,
                exit_code=1,
                stderr="fatal error",
            ),
        )
        feedback = generate_escalation_message(
            build_test_result=result,
            retry_count=3,
        )
        markdown = feedback.to_markdown()
        assert "##" in markdown
        assert "TASK-001" in markdown
