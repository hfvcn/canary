"""
Ralph Daemon - CLI Entry Point

Provides commands to start, stop, and check status of the Ralph daemon.
Ralph monitors git repositories for commits and orchestrates workflows.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional
import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from . import __version__
from .git_watcher import GitWatcher, GitWatcherConfig
from .message_bus import MessageBus, EventType, Event, get_message_bus

# CLI 应用
app = typer.Typer(
    name="ralph",
    help="Ralph Daemon - Git commit monitoring and workflow orchestration",
    add_completion=False,
)

console = Console()

# 全局状态
_daemon_running = False
_shutdown_event: asyncio.Event | None = None


def setup_logging(verbose: bool = False) -> None:
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def version_callback(value: bool) -> None:
    """显示版本信息"""
    if value:
        console.print(f"Ralph Daemon v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Ralph Daemon - Git commit monitoring and workflow orchestration"""
    pass


@app.command()
def start(
    repo_path: Path = typer.Argument(
        Path("."),
        help="Path to the git repository to monitor",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    poll_interval: float = typer.Option(
        2.0,
        "--interval",
        "-i",
        help="Polling interval in seconds",
        min=0.5,
        max=60.0,
    ),
    branch: Optional[str] = typer.Option(
        None,
        "--branch",
        "-b",
        help="Branch to monitor (default: current branch)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-V",
        help="Enable verbose logging",
    ),
) -> None:
    """
    Start the Ralph daemon.
    
    Monitors the specified git repository for new commits and publishes
    events to the message bus for workflow orchestration.
    """
    setup_logging(verbose)
    
    console.print(f"[bold green]Starting Ralph Daemon v{__version__}[/bold green]")
    console.print(f"  Repository: {repo_path}")
    console.print(f"  Poll interval: {poll_interval}s")
    if branch:
        console.print(f"  Branch: {branch}")
    
    try:
        asyncio.run(_run_daemon(repo_path, poll_interval, branch))
    except KeyboardInterrupt:
        console.print("\n[yellow]Shutdown requested[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)
    
    console.print("[green]Ralph Daemon stopped[/green]")


async def _run_daemon(
    repo_path: Path,
    poll_interval: float,
    branch: str | None,
) -> None:
    """运行守护进程主循环"""
    global _daemon_running, _shutdown_event
    
    _shutdown_event = asyncio.Event()
    
    # 设置信号处理
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: _shutdown_event.set())
    
    # 初始化组件
    message_bus = get_message_bus()
    
    config = GitWatcherConfig(
        repo_path=repo_path,
        poll_interval_seconds=poll_interval,
        branch=branch,
    )
    watcher = GitWatcher(config, message_bus)
    
    # 注册示例事件处理器（用于调试）
    async def log_commit(event: Event) -> None:
        console.print(
            f"[cyan]Commit:[/cyan] {event.payload.get('hash', '')[:8]} - "
            f"{event.payload.get('message', '')[:50]}"
        )
    
    message_bus.subscribe(EventType.GIT_COMMIT, log_commit)
    
    # 启动
    await message_bus.start()
    await watcher.start()
    
    _daemon_running = True
    console.print("[bold green]Daemon is running. Press Ctrl+C to stop.[/bold green]")
    
    # 等待关闭信号
    await _shutdown_event.wait()
    
    # 优雅关闭
    console.print("[yellow]Shutting down...[/yellow]")
    await watcher.stop()
    await message_bus.stop()
    
    _daemon_running = False


@app.command()
def stop() -> None:
    """
    Stop the Ralph daemon.
    
    Sends a stop signal to the running daemon process.
    Note: This is a placeholder for future IPC implementation.
    """
    console.print("[yellow]Stop command is not yet implemented.[/yellow]")
    console.print("To stop the daemon, use Ctrl+C in the terminal where it's running,")
    console.print("or send SIGTERM to the process.")
    raise typer.Exit(1)


@app.command()
def status() -> None:
    """
    Show the status of the Ralph daemon.
    
    Displays whether the daemon is running and its current state.
    Note: This is a placeholder for future IPC implementation.
    """
    console.print("[bold]Ralph Daemon Status[/bold]")
    console.print("─" * 40)
    
    # TODO: 实现进程间通信来检查守护进程状态
    # 目前只显示静态信息
    console.print(f"  Version: {__version__}")
    console.print("  Status: [yellow]Unknown[/yellow] (IPC not implemented)")
    console.print()
    console.print("[dim]Note: Full status reporting requires IPC implementation.[/dim]")


@app.command()
def watch(
    repo_path: Path = typer.Argument(
        Path("."),
        help="Path to the git repository",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
    count: int = typer.Option(
        10,
        "--count",
        "-n",
        help="Number of recent commits to show",
        min=1,
        max=100,
    ),
) -> None:
    """
    Watch recent commits in a repository (debug command).
    
    Shows the most recent commits without starting the full daemon.
    """
    from git import Repo
    
    console.print(f"[bold]Recent commits in {repo_path}[/bold]")
    console.print("─" * 60)
    
    try:
        repo = Repo(repo_path)
        for commit in repo.iter_commits(max_count=count):
            date_str = commit.authored_datetime.strftime("%Y-%m-%d %H:%M")
            msg = commit.message.strip().split("\n")[0][:50]
            console.print(f"  {commit.hexsha[:8]} | {date_str} | {msg}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
