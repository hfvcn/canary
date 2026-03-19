"""
Feedback Generator - Generate retry and escalation messages for failures.

Provides human-readable feedback messages based on validation results,
helping Actors understand what went wrong and how to fix it.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .build_test import BuildTestResult, ValidationStatus, CommandResult
from .task_file import TaskStateResult, TaskState

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    """反馈类型"""
    RETRY = "retry"           # 建议重试
    ESCALATION = "escalation" # 需要人工介入
    INFO = "info"             # 仅供参考
    SUCCESS = "success"       # 验证通过


@dataclass
class FeedbackMessage:
    """
    反馈消息

    Attributes:
        type: 反馈类型
        title: 标题
        summary: 摘要
        details: 详细信息
        suggestions: 修复建议列表
        related_files: 相关文件列表
        retry_count: 已重试次数
        max_retries: 最大重试次数
        timestamp: 生成时间
    """
    type: FeedbackType
    title: str
    summary: str
    details: str = ""
    suggestions: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def can_retry(self) -> bool:
        """是否可以重试"""
        return self.type == FeedbackType.RETRY and self.retry_count < self.max_retries

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value,
            "title": self.title,
            "summary": self.summary,
            "details": self.details,
            "suggestions": self.suggestions,
            "related_files": self.related_files,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "can_retry": self.can_retry,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        lines = [
            f"## {self.title}",
            "",
            self.summary,
        ]

        if self.details:
            lines.extend(["", "### 详细信息", "", self.details])

        if self.suggestions:
            lines.extend(["", "### 修复建议", ""])
            for i, suggestion in enumerate(self.suggestions, 1):
                lines.append(f"{i}. {suggestion}")

        if self.related_files:
            lines.extend(["", "### 相关文件", ""])
            for file in self.related_files:
                lines.append(f"- `{file}`")

        if self.can_retry:
            lines.extend([
                "",
                f"---",
                f"⚠️ 重试次数: {self.retry_count}/{self.max_retries}",
            ])

        return "\n".join(lines)


def _extract_error_details(result: CommandResult) -> tuple[str, list[str]]:
    """从命令结果中提取错误详情和建议"""
    details = ""
    suggestions = []

    if result.status == ValidationStatus.TIMEOUT:
        details = f"命令执行超时（{result.duration:.1f}秒）"
        suggestions = [
            "检查是否存在无限循环或死锁",
            "考虑增加超时时间",
            "分解为更小的测试单元",
        ]

    elif result.status == ValidationStatus.ERROR:
        details = result.error_message or "执行过程中发生错误"
        suggestions = [
            "检查命令语法是否正确",
            "确认所需依赖已安装",
            "检查工作目录是否正确",
        ]

    elif result.status == ValidationStatus.FAIL:
        # 分析 stderr/stdout 提取关键信息
        output = result.stderr or result.stdout
        if output:
            # 截取最后 500 字符作为摘要
            details = output[-500:] if len(output) > 500 else output

        # 根据输出内容生成建议
        output_lower = output.lower() if output else ""

        if "import" in output_lower and "error" in output_lower:
            suggestions.append("检查导入语句和依赖项")
        if "syntax" in output_lower:
            suggestions.append("修复语法错误")
        if "assertion" in output_lower or "assert" in output_lower:
            suggestions.append("检查断言失败的原因，确认预期值是否正确")
        if "permission" in output_lower:
            suggestions.append("检查文件权限")
        if "not found" in output_lower:
            suggestions.append("检查缺失的文件或依赖")

        if not suggestions:
            suggestions = [
                "仔细阅读错误输出",
                "检查最近的代码变更",
                "运行单个测试以定位问题",
            ]

    return details, suggestions


def generate_retry_message(
    build_test_result: BuildTestResult | None = None,
    task_state_result: TaskStateResult | None = None,
    retry_count: int = 0,
    max_retries: int = 3,
) -> FeedbackMessage:
    """
    生成重试消息

    根据验证结果生成适合 Actor 阅读的重试消息。

    Args:
        build_test_result: 构建/测试验证结果
        task_state_result: 任务状态检查结果
        retry_count: 已重试次数
        max_retries: 最大重试次数

    Returns:
        FeedbackMessage 重试消息
    """
    issues = []
    suggestions = []
    related_files = []
    details_parts = []

    # 处理构建/测试结果
    if build_test_result:
        # 构建失败
        if build_test_result.build_result and not build_test_result.build_result.passed:
            issues.append("构建失败")
            error_details, error_suggestions = _extract_error_details(
                build_test_result.build_result
            )
            details_parts.append(f"**构建错误:**\n```\n{error_details}\n```")
            suggestions.extend(error_suggestions)

        # 测试失败
        if build_test_result.test_result and not build_test_result.test_result.passed:
            issues.append("测试失败")
            error_details, error_suggestions = _extract_error_details(
                build_test_result.test_result
            )
            details_parts.append(f"**测试错误:**\n```\n{error_details}\n```")
            suggestions.extend(error_suggestions)

        # Lint 失败（非阻塞但提供建议）
        if build_test_result.lint_result and not build_test_result.lint_result.passed:
            if build_test_result.lint_result.status != ValidationStatus.SKIP:
                issues.append("Lint 警告")
                error_details, error_suggestions = _extract_error_details(
                    build_test_result.lint_result
                )
                details_parts.append(f"**Lint 警告:**\n```\n{error_details}\n```")

    # 处理任务状态结果
    if task_state_result and not task_state_result.is_valid:
        issues.extend(task_state_result.issues)
        suggestions.append("更新 state.json 文件以反映正确的任务状态")

    # 构建消息
    if not issues:
        return FeedbackMessage(
            type=FeedbackType.SUCCESS,
            title="✅ 验证通过",
            summary="所有验证检查都已通过。",
        )

    title = f"⚠️ 验证失败: {', '.join(issues[:2])}"
    if len(issues) > 2:
        title += f" (+{len(issues) - 2} 个问题)"

    summary = f"任务 {build_test_result.task_id if build_test_result else 'unknown'} 的验证未通过。"
    if retry_count < max_retries:
        summary += f" 请修复以下问题后重试（{retry_count + 1}/{max_retries}）。"

    # 去重建议
    suggestions = list(dict.fromkeys(suggestions))

    return FeedbackMessage(
        type=FeedbackType.RETRY if retry_count < max_retries else FeedbackType.ESCALATION,
        title=title,
        summary=summary,
        details="\n\n".join(details_parts),
        suggestions=suggestions[:5],  # 最多 5 条建议
        related_files=related_files,
        retry_count=retry_count,
        max_retries=max_retries,
    )


def generate_escalation_message(
    build_test_result: BuildTestResult | None = None,
    task_state_result: TaskStateResult | None = None,
    retry_count: int = 0,
    reason: str = "",
) -> FeedbackMessage:
    """
    生成升级消息

    当问题无法通过重试解决时，生成需要人工介入的消息。

    Args:
        build_test_result: 构建/测试验证结果
        task_state_result: 任务状态检查结果
        retry_count: 已尝试的重试次数
        reason: 升级原因

    Returns:
        FeedbackMessage 升级消息
    """
    task_id = build_test_result.task_id if build_test_result else "unknown"

    # 收集所有问题
    issues = []
    details_parts = []

    if build_test_result:
        if build_test_result.build_result and not build_test_result.build_result.passed:
            issues.append("构建失败")
            result = build_test_result.build_result
            details_parts.append(
                f"**构建失败 ({result.status.value})**:\n"
                f"退出码: {result.exit_code}\n"
                f"```\n{result.stderr or result.stdout or '无输出'}\n```"
            )

        if build_test_result.test_result and not build_test_result.test_result.passed:
            issues.append("测试失败")
            result = build_test_result.test_result
            details_parts.append(
                f"**测试失败 ({result.status.value})**:\n"
                f"退出码: {result.exit_code}\n"
                f"```\n{result.stderr or result.stdout or '无输出'}\n```"
            )

    if task_state_result and not task_state_result.is_valid:
        issues.extend(task_state_result.issues)
        details_parts.append(f"**状态检查问题**:\n- " + "\n- ".join(task_state_result.issues))

    title = f"🚨 需要人工介入: 任务 {task_id}"

    summary_parts = [f"任务 {task_id} 在 {retry_count} 次尝试后仍未能通过验证。"]
    if reason:
        summary_parts.append(f"升级原因: {reason}")
    summary_parts.append("需要人工检查和介入。")

    suggestions = [
        "检查环境配置是否正确",
        "确认测试用例本身是否有问题",
        "考虑是否需要调整任务范围",
        "联系相关团队成员协助排查",
    ]

    return FeedbackMessage(
        type=FeedbackType.ESCALATION,
        title=title,
        summary=" ".join(summary_parts),
        details="\n\n".join(details_parts),
        suggestions=suggestions,
        retry_count=retry_count,
        max_retries=retry_count,  # 已达到上限
    )


class FeedbackGenerator:
    """
    反馈生成器

    根据验证结果生成适合 Actor 阅读的反馈消息。

    示例:
        generator = FeedbackGenerator(max_retries=3)

        feedback = generator.generate(
            build_test_result=result,
            retry_count=1,
        )

        if feedback.can_retry:
            print(feedback.to_markdown())
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self._retry_counts: dict[str, int] = {}

    def generate(
        self,
        build_test_result: BuildTestResult | None = None,
        task_state_result: TaskStateResult | None = None,
        task_id: str | None = None,
    ) -> FeedbackMessage:
        """
        生成反馈消息

        自动跟踪重试次数并决定生成重试消息还是升级消息。

        Args:
            build_test_result: 构建/测试验证结果
            task_state_result: 任务状态检查结果
            task_id: 任务 ID（用于跟踪重试次数）

        Returns:
            FeedbackMessage 反馈消息
        """
        # 确定任务 ID
        if task_id is None:
            if build_test_result:
                task_id = build_test_result.task_id
            elif task_state_result:
                task_id = task_state_result.task_id
            else:
                task_id = "unknown"

        # 检查是否全部通过
        all_passed = True
        if build_test_result and not build_test_result.overall_passed:
            all_passed = False
        if task_state_result and not task_state_result.is_valid:
            all_passed = False

        if all_passed:
            # 重置重试计数
            if task_id in self._retry_counts:
                del self._retry_counts[task_id]
            return FeedbackMessage(
                type=FeedbackType.SUCCESS,
                title="✅ 验证通过",
                summary=f"任务 {task_id} 的所有验证检查都已通过。",
            )

        # 更新重试计数
        retry_count = self._retry_counts.get(task_id, 0)
        self._retry_counts[task_id] = retry_count + 1

        # 决定是重试还是升级
        if retry_count < self.max_retries:
            return generate_retry_message(
                build_test_result=build_test_result,
                task_state_result=task_state_result,
                retry_count=retry_count,
                max_retries=self.max_retries,
            )
        else:
            return generate_escalation_message(
                build_test_result=build_test_result,
                task_state_result=task_state_result,
                retry_count=retry_count,
                reason="已达到最大重试次数",
            )

    def reset(self, task_id: str) -> None:
        """重置任务的重试计数"""
        if task_id in self._retry_counts:
            del self._retry_counts[task_id]

    def reset_all(self) -> None:
        """重置所有重试计数"""
        self._retry_counts.clear()

    def get_retry_count(self, task_id: str) -> int:
        """获取任务的重试次数"""
        return self._retry_counts.get(task_id, 0)
