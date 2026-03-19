"""
Build/Test Validator - Execute and verify build, test, and lint commands.

This is the **required** validation layer (Layer 1 in the design spec).
Provides machine-verifiable validation through executable commands.
"""

import asyncio
import logging
import os
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .config import ValidatorConfig, CommandConfig

logger = logging.getLogger(__name__)


class ValidationStatus(str, Enum):
    """验证状态"""
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"      # 未配置或跳过
    TIMEOUT = "timeout"
    ERROR = "error"    # 执行错误（非测试失败）


@dataclass
class CommandResult:
    """
    单个命令的执行结果

    Attributes:
        command: 执行的命令
        status: 执行状态
        exit_code: 退出码（None 表示未执行或超时）
        stdout: 标准输出
        stderr: 标准错误
        duration: 执行时间（秒）
        error_message: 错误信息（如果有）
    """
    command: str
    status: ValidationStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration: float = 0.0
    error_message: str | None = None

    @property
    def passed(self) -> bool:
        """是否通过"""
        return self.status == ValidationStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "command": self.command,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "stdout": self.stdout[:1000] if self.stdout else "",  # 截断长输出
            "stderr": self.stderr[:1000] if self.stderr else "",
            "duration": self.duration,
            "error_message": self.error_message,
        }


@dataclass
class BuildTestResult:
    """
    构建/测试验证的完整结果

    Attributes:
        task_id: 任务 ID
        commit_hash: 提交哈希
        build_result: 构建结果
        test_result: 测试结果
        lint_result: Lint 结果
        timestamp: 验证时间
        overall_passed: 是否整体通过（必选验证全部通过）
    """
    task_id: str
    commit_hash: str
    build_result: CommandResult | None = None
    test_result: CommandResult | None = None
    lint_result: CommandResult | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def overall_passed(self) -> bool:
        """检查是否整体通过（仅检查必选验证）"""
        results = [self.build_result, self.test_result]
        for result in results:
            if result and result.status not in (ValidationStatus.PASS, ValidationStatus.SKIP):
                return False
        return True

    @property
    def build_passed(self) -> bool:
        """构建是否通过"""
        return self.build_result is None or self.build_result.passed

    @property
    def test_passed(self) -> bool:
        """测试是否通过"""
        return self.test_result is None or self.test_result.passed

    @property
    def lint_passed(self) -> bool:
        """Lint 是否通过"""
        return self.lint_result is None or self.lint_result.passed

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "commit_hash": self.commit_hash,
            "build": self.build_result.to_dict() if self.build_result else None,
            "test": self.test_result.to_dict() if self.test_result else None,
            "lint": self.lint_result.to_dict() if self.lint_result else None,
            "timestamp": self.timestamp.isoformat(),
            "overall_passed": self.overall_passed,
        }


async def _run_command(
    command: str,
    working_dir: Path,
    timeout: float,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """
    执行单个命令

    Args:
        command: 命令字符串
        working_dir: 工作目录
        timeout: 超时时间（秒）
        env: 额外环境变量

    Returns:
        CommandResult 执行结果
    """
    start_time = datetime.now()

    # 合并环境变量
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    try:
        # 使用 shell 执行命令（支持管道、重定向等）
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=working_dir,
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            duration = (datetime.now() - start_time).total_seconds()

            exit_code = process.returncode
            status = ValidationStatus.PASS if exit_code == 0 else ValidationStatus.FAIL

            return CommandResult(
                command=command,
                status=status,
                exit_code=exit_code,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration=duration,
            )

        except asyncio.TimeoutError:
            # 超时，终止进程
            process.kill()
            await process.wait()
            duration = (datetime.now() - start_time).total_seconds()

            return CommandResult(
                command=command,
                status=ValidationStatus.TIMEOUT,
                duration=duration,
                error_message=f"Command timed out after {timeout}s",
            )

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Command execution error: {e}")

        return CommandResult(
            command=command,
            status=ValidationStatus.ERROR,
            duration=duration,
            error_message=str(e),
        )


async def run_build(
    config: ValidatorConfig,
    changed_files: list[str] | None = None,
) -> CommandResult:
    """
    执行构建验证

    Args:
        config: 验证器配置
        changed_files: 变更的文件列表（可选，用于增量构建）

    Returns:
        CommandResult 构建结果
    """
    if not config.build_command:
        logger.debug("Build command not configured, skipping")
        return CommandResult(
            command="",
            status=ValidationStatus.SKIP,
        )

    cmd_config = config.build_command
    working_dir = config.project_root / cmd_config.working_dir

    logger.info(f"Running build: {cmd_config.command}")

    return await _run_command(
        command=cmd_config.command,
        working_dir=working_dir,
        timeout=cmd_config.timeout,
        env=cmd_config.env,
    )


async def run_tests(
    config: ValidatorConfig,
    changed_files: list[str] | None = None,
) -> CommandResult:
    """
    执行测试验证

    Args:
        config: 验证器配置
        changed_files: 变更的文件列表（可选，用于增量测试）

    Returns:
        CommandResult 测试结果
    """
    if not config.test_command:
        logger.debug("Test command not configured, skipping")
        return CommandResult(
            command="",
            status=ValidationStatus.SKIP,
        )

    cmd_config = config.test_command
    working_dir = config.project_root / cmd_config.working_dir

    logger.info(f"Running tests: {cmd_config.command}")

    return await _run_command(
        command=cmd_config.command,
        working_dir=working_dir,
        timeout=cmd_config.timeout,
        env=cmd_config.env,
    )


async def run_lint(
    config: ValidatorConfig,
    changed_files: list[str] | None = None,
) -> CommandResult:
    """
    执行 Lint 验证

    Args:
        config: 验证器配置
        changed_files: 变更的文件列表（可选，用于增量 lint）

    Returns:
        CommandResult Lint 结果
    """
    if not config.lint_command:
        logger.debug("Lint command not configured, skipping")
        return CommandResult(
            command="",
            status=ValidationStatus.SKIP,
        )

    cmd_config = config.lint_command
    working_dir = config.project_root / cmd_config.working_dir

    logger.info(f"Running lint: {cmd_config.command}")

    return await _run_command(
        command=cmd_config.command,
        working_dir=working_dir,
        timeout=cmd_config.timeout,
        env=cmd_config.env,
    )


class BuildTestValidator:
    """
    构建/测试验证器

    监听 Git 提交事件，执行验证命令，发送结果到 CCCC Daemon。

    示例:
        config = ValidatorConfig.default_for_python(Path("."))
        validator = BuildTestValidator(config)

        result = await validator.validate(
            task_id="TASK-001",
            commit_hash="abc123",
            changed_files=["src/main.py"],
        )

        if result.overall_passed:
            print("Validation passed!")
    """

    def __init__(self, config: ValidatorConfig):
        self.config = config

    async def validate(
        self,
        task_id: str,
        commit_hash: str,
        changed_files: list[str] | None = None,
    ) -> BuildTestResult:
        """
        执行完整的构建/测试验证

        Args:
            task_id: 任务 ID
            commit_hash: 提交哈希
            changed_files: 变更的文件列表

        Returns:
            BuildTestResult 完整验证结果
        """
        logger.info(f"Starting validation for task {task_id}, commit {commit_hash[:8]}")

        # 并行执行所有验证
        build_task = run_build(self.config, changed_files)
        test_task = run_tests(self.config, changed_files)
        lint_task = run_lint(self.config, changed_files)

        build_result, test_result, lint_result = await asyncio.gather(
            build_task, test_task, lint_task
        )

        result = BuildTestResult(
            task_id=task_id,
            commit_hash=commit_hash,
            build_result=build_result,
            test_result=test_result,
            lint_result=lint_result,
        )

        # 记录验证结果
        if result.overall_passed:
            logger.info(f"Validation passed for task {task_id}")
        else:
            logger.warning(f"Validation failed for task {task_id}")
            if build_result and not build_result.passed:
                logger.warning(f"  - Build: {build_result.status.value}")
            if test_result and not test_result.passed:
                logger.warning(f"  - Test: {test_result.status.value}")
            if lint_result and not lint_result.passed:
                logger.info(f"  - Lint: {lint_result.status.value} (non-blocking)")

        return result

    async def validate_and_send(
        self,
        task_id: str,
        commit_hash: str,
        changed_files: list[str] | None = None,
        ipc_client: Any = None,
    ) -> BuildTestResult:
        """
        执行验证并通过 IPC 发送结果

        Args:
            task_id: 任务 ID
            commit_hash: 提交哈希
            changed_files: 变更的文件列表
            ipc_client: IPC 客户端（可选）

        Returns:
            BuildTestResult 验证结果
        """
        result = await self.validate(task_id, commit_hash, changed_files)

        # 发送到 CCCC Daemon
        await self._send_verification_result(result, ipc_client)

        return result

    async def _send_verification_result(
        self,
        result: BuildTestResult,
        ipc_client: Any = None,
    ) -> bool:
        """通过 IPC 发送验证结果"""
        # 延迟导入以避免循环依赖
        from ..ipc import VerificationResult, get_ipc_client

        if ipc_client is None:
            ipc_client = get_ipc_client()

        message = VerificationResult(
            task_id=result.task_id,
            commit_hash=result.commit_hash,
            build_passed=result.build_passed,
            test_passed=result.test_passed,
            lint_passed=result.lint_passed,
            details=result.to_dict(),
        )

        try:
            success = await ipc_client.send_message(message)
            if success:
                logger.info(f"Verification result sent for task {result.task_id}")
            else:
                logger.warning(f"Failed to send verification result for task {result.task_id}")
            return success
        except Exception as e:
            logger.error(f"Error sending verification result: {e}")
            return False
