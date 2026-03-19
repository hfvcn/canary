"""Tests for GitWatcher module."""

import asyncio
import tempfile
from pathlib import Path
from datetime import datetime

import pytest
from git import Repo

from ralph.git_watcher import GitWatcher, GitWatcherConfig, ParsedCommit
from ralph.message_bus import MessageBus, EventType, Event


class TestParsedCommit:
    """ParsedCommit 数据类测试"""
    
    def test_create_parsed_commit(self):
        """测试创建 ParsedCommit"""
        commit = ParsedCommit(
            hash="abc123def456",
            branch="main",
            message="Test commit message",
            author="Test Author",
            authored_date=datetime.now(),
        )
        
        assert commit.hash == "abc123def456"
        assert commit.branch == "main"
        assert commit.message == "Test commit message"
        assert commit.author == "Test Author"


class TestGitWatcherConfig:
    """GitWatcherConfig 测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = GitWatcherConfig(repo_path=Path("."))
        
        assert config.repo_path == Path(".")
        assert config.poll_interval_seconds == 2.0
        assert config.branch is None
        
    def test_custom_config(self):
        """测试自定义配置"""
        config = GitWatcherConfig(
            repo_path=Path("/tmp/repo"),
            poll_interval_seconds=5.0,
            branch="develop",
        )
        
        assert config.repo_path == Path("/tmp/repo")
        assert config.poll_interval_seconds == 5.0
        assert config.branch == "develop"


class TestGitWatcher:
    """GitWatcher 集成测试"""
    
    @pytest.fixture
    def temp_repo(self):
        """创建临时 Git 仓库"""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            repo = Repo.init(repo_path)
            
            # 配置 git 用户（避免 git commit 报错）
            repo.config_writer().set_value("user", "name", "Test").release()
            repo.config_writer().set_value("user", "email", "test@test.com").release()
            
            # 创建初始提交
            readme = repo_path / "README.md"
            readme.write_text("# Test Repo")
            repo.index.add(["README.md"])
            repo.index.commit("Initial commit")
            
            yield repo_path, repo
            
    @pytest.fixture
    def message_bus(self):
        """创建消息总线"""
        return MessageBus()
        
    def test_validate_repo_valid(self, temp_repo):
        """测试验证有效仓库"""
        repo_path, _ = temp_repo
        config = GitWatcherConfig(repo_path=repo_path)
        watcher = GitWatcher(config)
        
        repo = watcher._validate_repo()
        assert repo is not None
        repo.close()
        
    def test_validate_repo_not_exists(self):
        """测试验证不存在的路径"""
        config = GitWatcherConfig(repo_path=Path("/nonexistent/path"))
        watcher = GitWatcher(config)
        
        with pytest.raises(ValueError, match="does not exist"):
            watcher._validate_repo()
            
    def test_validate_repo_not_git(self):
        """测试验证非 Git 目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = GitWatcherConfig(repo_path=Path(tmpdir))
            watcher = GitWatcher(config)
            
            with pytest.raises(ValueError, match="missing .git"):
                watcher._validate_repo()
                
    @pytest.mark.asyncio
    async def test_start_stop(self, temp_repo, message_bus):
        """测试启动和停止"""
        repo_path, _ = temp_repo
        config = GitWatcherConfig(
            repo_path=repo_path,
            poll_interval_seconds=0.1,
        )
        watcher = GitWatcher(config, message_bus)
        
        assert not watcher.is_running
        
        await watcher.start()
        assert watcher.is_running
        assert watcher.last_commit_hash is not None
        
        await watcher.stop()
        assert not watcher.is_running
        
    @pytest.mark.asyncio
    async def test_detect_new_commit(self, temp_repo, message_bus):
        """测试检测新提交"""
        repo_path, repo = temp_repo
        config = GitWatcherConfig(
            repo_path=repo_path,
            poll_interval_seconds=0.1,
        )
        watcher = GitWatcher(config, message_bus)
        
        # 收集事件
        events: list[Event] = []
        
        async def collect_events(event: Event):
            events.append(event)
            
        message_bus.subscribe(EventType.GIT_COMMIT, collect_events)
        
        await message_bus.start()
        await watcher.start()
        
        initial_hash = watcher.last_commit_hash
        
        # 创建新提交
        test_file = repo_path / "test.txt"
        test_file.write_text("test content")
        repo.index.add(["test.txt"])
        new_commit = repo.index.commit("Add test file")
        
        # 等待轮询检测
        await asyncio.sleep(0.3)
        
        await watcher.stop()
        await message_bus.stop()
        
        # 验证检测到新提交
        assert watcher.last_commit_hash == new_commit.hexsha
        assert watcher.last_commit_hash != initial_hash
        
        # 验证事件发布
        assert len(events) >= 1
        commit_event = events[-1]
        assert commit_event.payload["hash"] == new_commit.hexsha
        assert "Add test file" in commit_event.payload["message"]


class TestMessageBusIntegration:
    """MessageBus 集成测试"""
    
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        """测试发布订阅"""
        bus = MessageBus()
        received: list[Event] = []
        
        async def handler(event: Event):
            received.append(event)
            
        bus.subscribe(EventType.GIT_COMMIT, handler)
        
        await bus.start()
        
        from ralph.message_bus import GitCommitEvent
        event = GitCommitEvent(
            commit_hash="abc123",
            branch="main",
            message="Test",
            author="Author",
        )
        await bus.publish(event)
        
        # 等待处理
        await asyncio.sleep(0.1)
        
        await bus.stop()
        
        assert len(received) == 1
        assert received[0].payload["hash"] == "abc123"
