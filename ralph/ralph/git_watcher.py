"""
Git Watcher - Monitor git repository for new commits.

Polls the git repository at configurable intervals and publishes
events when new commits are detected. Inspired by gitcortex's
git_watcher implementation.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import logging

from git import Repo, InvalidGitRepositoryError, GitCommandError
from git.objects.commit import Commit

from .message_bus import MessageBus, GitCommitEvent, EventType, Event, get_message_bus

logger = logging.getLogger(__name__)


@dataclass
class GitWatcherConfig:
    """Git Watcher 配置"""
    repo_path: Path
    poll_interval_seconds: float = 2.0
    branch: str | None = None  # None 表示监控当前分支


@dataclass
class ParsedCommit:
    """解析后的提交信息"""
    hash: str
    branch: str
    message: str
    author: str
    authored_date: datetime
    
    @classmethod
    def from_git_commit(cls, commit: Commit, branch: str) -> "ParsedCommit":
        """从 gitpython Commit 对象创建"""
        return cls(
            hash=commit.hexsha,
            branch=branch,
            message=commit.message.strip(),
            author=str(commit.author),
            authored_date=commit.authored_datetime,
        )


class GitWatcher:
    """
    Git 仓库监控器
    
    使用轮询方式检测新提交，并通过消息总线发布事件。
    
    特性:
    - 轮询检测新提交
    - 记录最后处理的提交 hash，避免重复处理
    - 支持指定分支监控
    - 优雅启停
    
    示例:
        config = GitWatcherConfig(repo_path=Path("."))
        watcher = GitWatcher(config)
        
        await watcher.start()
        # ... 运行一段时间
        await watcher.stop()
    """
    
    def __init__(
        self, 
        config: GitWatcherConfig,
        message_bus: MessageBus | None = None
    ):
        self.config = config
        self.message_bus = message_bus or get_message_bus()
        
        self._repo: Repo | None = None
        self._last_commit_hash: str | None = None
        self._running = False
        self._watch_task: asyncio.Task | None = None
        
    def _validate_repo(self) -> Repo:
        """验证并打开 Git 仓库"""
        repo_path = self.config.repo_path
        
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")
            
        if not repo_path.is_dir():
            raise ValueError(f"Repository path is not a directory: {repo_path}")
            
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            raise ValueError(f"Not a git repository (missing .git): {repo_path}")
            
        try:
            return Repo(repo_path)
        except InvalidGitRepositoryError as e:
            raise ValueError(f"Invalid git repository: {repo_path}") from e
            
    def _get_current_branch(self) -> str:
        """获取当前分支名"""
        if not self._repo:
            return "unknown"
            
        try:
            return self._repo.active_branch.name
        except TypeError:
            # detached HEAD
            return "HEAD"

    def _get_monitored_ref(self) -> str:
        """获取当前监控的 ref 名称。"""
        return self.config.branch or self._get_current_branch()

    def _get_ref_commit(self, ref_name: str) -> Commit:
        """读取指定 ref 的提交对象。"""
        assert self._repo is not None
        return self._repo.commit(ref_name)
            
    def _get_latest_commit(self) -> ParsedCommit | None:
        """获取最新提交"""
        if not self._repo:
            return None
            
        try:
            branch = self._get_monitored_ref()
            commit = self._get_ref_commit(branch)
            return ParsedCommit.from_git_commit(commit, branch)
        except Exception as e:
            logger.error(f"Failed to get latest commit: {e}")
            return None
            
    def _get_new_commits_since(self, last_hash: str | None) -> list[ParsedCommit]:
        """获取指定提交之后的所有新提交"""
        if not self._repo:
            return []
            
        try:
            branch = self._get_monitored_ref()
            
            if last_hash is None:
                # 首次运行，只返回最新提交
                commit = self._get_ref_commit(branch)
                return [ParsedCommit.from_git_commit(commit, branch)]
                
            # 获取从 last_hash 到监控分支 tip 的所有提交
            commits = []
            for commit in self._repo.iter_commits(f"{last_hash}..{branch}"):
                commits.append(ParsedCommit.from_git_commit(commit, branch))
                
            # 反转以保持时间顺序（旧的在前）
            return list(reversed(commits))
            
        except GitCommandError as e:
            logger.error(f"Git command error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to get new commits: {e}")
            return []
            
    async def _poll_loop(self) -> None:
        """轮询循环"""
        while self._running:
            try:
                # 刷新仓库状态（检测外部变更）
                # 对于本地测试仓库，跳过 fetch（没有远程）
                if self._repo and self._repo.remotes:
                    try:
                        self._repo.git.fetch("--all", "--prune")
                    except GitCommandError:
                        # 忽略 fetch 错误（可能没有网络或远程不可用）
                        pass
                    
                new_commits = self._get_new_commits_since(self._last_commit_hash)
                
                for commit in new_commits:
                    logger.info(f"New commit detected: {commit.hash[:8]} - {commit.message[:50]}")
                    
                    # 发布事件
                    event = GitCommitEvent(
                        commit_hash=commit.hash,
                        branch=commit.branch,
                        message=commit.message,
                        author=commit.author,
                        payload={
                            "hash": commit.hash,
                            "branch": commit.branch,
                            "message": commit.message,
                            "author": commit.author,
                            "authored_date": commit.authored_date.isoformat(),
                        }
                    )
                    await self.message_bus.publish(event)
                    
                    # 更新最后处理的提交
                    self._last_commit_hash = commit.hash
                    
            except Exception as e:
                logger.error(f"Error in poll loop: {e}", exc_info=True)
                
            # 等待下一次轮询
            await asyncio.sleep(self.config.poll_interval_seconds)
            
    async def start(self) -> None:
        """启动监控"""
        if self._running:
            logger.warning("GitWatcher is already running")
            return
            
        # 验证并打开仓库
        self._repo = self._validate_repo()
        
        # 获取初始提交 hash
        initial_commit = self._get_latest_commit()
        if initial_commit:
            self._last_commit_hash = initial_commit.hash
            logger.info(f"Initial commit: {initial_commit.hash[:8]}")
            
        self._running = True
        self._watch_task = asyncio.create_task(self._poll_loop())
        
        logger.info(
            f"GitWatcher started for {self.config.repo_path} "
            f"(polling every {self.config.poll_interval_seconds}s)"
        )
        
    async def stop(self) -> None:
        """停止监控"""
        if not self._running:
            return
            
        self._running = False
        
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None
            
        if self._repo:
            self._repo.close()
            self._repo = None
            
        logger.info("GitWatcher stopped")
        
    @property
    def is_running(self) -> bool:
        return self._running
        
    @property
    def last_commit_hash(self) -> str | None:
        return self._last_commit_hash
