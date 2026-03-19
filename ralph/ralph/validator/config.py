"""
Validator Configuration.

Defines configuration options for the verification pipeline,
including command definitions and retry strategies.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CommandConfig:
    """
    可执行命令配置

    Attributes:
        command: 命令字符串（支持 shell 语法）
        timeout: 超时时间（秒）
        working_dir: 工作目录（相对于项目根目录）
        env: 额外环境变量
        required: 是否为必须通过的验证
    """
    command: str
    timeout: float = 300.0  # 默认 5 分钟
    working_dir: str = "."
    env: dict[str, str] = field(default_factory=dict)
    required: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandConfig":
        """从字典创建配置"""
        return cls(
            command=data["command"],
            timeout=data.get("timeout", 300.0),
            working_dir=data.get("working_dir", "."),
            env=data.get("env", {}),
            required=data.get("required", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "command": self.command,
            "timeout": self.timeout,
            "working_dir": self.working_dir,
            "env": self.env,
            "required": self.required,
        }


@dataclass
class ValidatorConfig:
    """
    验证器配置

    Attributes:
        project_root: 项目根目录
        build_command: 构建命令配置
        test_command: 测试命令配置
        lint_command: Lint 命令配置
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        enable_task_state_check: 是否启用任务状态检查
        cccc_dir: .cccc 目录路径（相对于项目根目录）
    """
    project_root: Path
    build_command: CommandConfig | None = None
    test_command: CommandConfig | None = None
    lint_command: CommandConfig | None = None
    max_retries: int = 3
    retry_delay: float = 5.0
    enable_task_state_check: bool = True
    cccc_dir: str = ".cccc"

    def __post_init__(self):
        """初始化后处理"""
        # 确保 project_root 是 Path 对象
        if isinstance(self.project_root, str):
            self.project_root = Path(self.project_root)

    @property
    def cccc_path(self) -> Path:
        """获取 .cccc 目录的完整路径"""
        return self.project_root / self.cccc_dir

    @property
    def actors_path(self) -> Path:
        """获取 actors 目录路径"""
        return self.cccc_path / "actors"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ValidatorConfig":
        """从字典创建配置"""
        build_cmd = data.get("build_command")
        test_cmd = data.get("test_command")
        lint_cmd = data.get("lint_command")

        return cls(
            project_root=Path(data["project_root"]),
            build_command=CommandConfig.from_dict(build_cmd) if build_cmd else None,
            test_command=CommandConfig.from_dict(test_cmd) if test_cmd else None,
            lint_command=CommandConfig.from_dict(lint_cmd) if lint_cmd else None,
            max_retries=data.get("max_retries", 3),
            retry_delay=data.get("retry_delay", 5.0),
            enable_task_state_check=data.get("enable_task_state_check", True),
            cccc_dir=data.get("cccc_dir", ".cccc"),
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "project_root": str(self.project_root),
            "build_command": self.build_command.to_dict() if self.build_command else None,
            "test_command": self.test_command.to_dict() if self.test_command else None,
            "lint_command": self.lint_command.to_dict() if self.lint_command else None,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "enable_task_state_check": self.enable_task_state_check,
            "cccc_dir": self.cccc_dir,
        }

    @classmethod
    def default_for_python(cls, project_root: Path) -> "ValidatorConfig":
        """创建 Python 项目的默认配置"""
        return cls(
            project_root=project_root,
            build_command=CommandConfig(
                command="python -m py_compile $(git diff --name-only --cached --diff-filter=AM -- '*.py')",
                timeout=60.0,
            ),
            test_command=CommandConfig(
                command="pytest -x -q",
                timeout=300.0,
            ),
            lint_command=CommandConfig(
                command="ruff check .",
                timeout=60.0,
                required=False,  # lint 失败不阻塞
            ),
        )

    @classmethod
    def default_for_node(cls, project_root: Path) -> "ValidatorConfig":
        """创建 Node.js 项目的默认配置"""
        return cls(
            project_root=project_root,
            build_command=CommandConfig(
                command="npm run build",
                timeout=300.0,
            ),
            test_command=CommandConfig(
                command="npm test",
                timeout=300.0,
            ),
            lint_command=CommandConfig(
                command="npm run lint",
                timeout=60.0,
                required=False,
            ),
        )
