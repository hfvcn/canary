"""Runtime detection and configuration for agent CLIs."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..util.process import find_subprocess_executable


@dataclass
class RuntimeInfo:
    """Information about an agent runtime."""
    name: str
    display_name: str
    command: str
    available: bool
    path: Optional[str]
    capabilities: str
    mcp_add_command: Optional[List[str]]  # Command to add MCP server, None if manual config required
    # From runtime pool (if configured)
    priority: int = 999
    scenarios: List[str] = None  # type: ignore
    
    def __post_init__(self) -> None:
        if self.scenarios is None:
            self.scenarios = []


# Known agent runtimes with their configurations
KNOWN_RUNTIMES: Dict[str, Dict[str, Any]] = {
    "amp": {
        "display_name": "Amp",
        "command": "amp",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "amp mcp add {name} {cmd}",
    },
    "auggie": {
        "display_name": "Auggie (Augment)",
        "command": "auggie",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "auggie mcp add {name} -- {cmd}",
    },
    "claude": {
        "display_name": "Claude Code",
        "command": "claude",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "claude mcp add -s user {name} -- {cmd}",
    },
    "codex": {
        "display_name": "Codex CLI",
        "command": "codex",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "codex mcp add {name} -- {cmd}",
    },
    "droid": {
        "display_name": "Droid CLI",
        "command": "droid",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "droid mcp add --type stdio {name} {cmd}",
    },
    "gemini": {
        "display_name": "Gemini CLI",
        "command": "gemini",
        "command_candidates": ["ge", "gemini"],
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "gemini mcp add -s user {name} {cmd}",
    },
    "kimi": {
        "display_name": "Kimi CLI",
        "command": "kimi",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "kimi mcp add --transport stdio {name} -- {cmd}",
    },
    "neovate": {
        "display_name": "Neovate Code",
        "command": "neovate",
        "capabilities": "MCP; MCP setup: auto",
        "mcp_add_pattern": "neovate mcp add -g {name} {cmd}",
    },
    "custom": {
        "display_name": "Custom Runtime",
        "command": "custom",
        "capabilities": "MCP; MCP setup: manual",
        "mcp_add_pattern": None,
    },
}

# First-class supported runtimes (CCCC manages startup defaults + MCP wiring)
PRIMARY_RUNTIMES = ["claude", "codex", "droid", "amp", "auggie", "neovate", "gemini", "kimi"]


def _normalize_command_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if isinstance(item, str) and str(item).strip()]


def resolve_runtime_executable(name: str) -> str:
    """Resolve the executable used for a runtime.

    For runtimes with command candidates, pick the first command found in PATH.
    """
    config = KNOWN_RUNTIMES.get(name)
    if not config:
        return name
    default_command = str(config.get("command") or name).strip() or name
    candidates = _normalize_command_list(config.get("command_candidates")) or [default_command]
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return default_command


@lru_cache(maxsize=8)
def _has_zsh_alias(alias_name: str) -> bool:
    try:
        result = subprocess.run(
            ["zsh", "-lic", f"alias {alias_name}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return False
    out = str(result.stdout or "").strip()
    if result.returncode != 0:
        return False
    return out.startswith(f"{alias_name}=") or f"alias {alias_name}=" in out


def _gemini_command_with_flags() -> List[str]:
    if shutil.which("ge"):
        return ["ge", "--yolo"]
    if _has_zsh_alias("ge"):
        # ge is often a zsh alias with proxy env exports; run through login shell so alias expands.
        return ["zsh", "-lic", "ge --yolo"]
    return [resolve_runtime_executable("gemini"), "--yolo"]


def detect_runtime(name: str) -> RuntimeInfo:
    """Detect if a specific runtime is available on the system."""
    config = KNOWN_RUNTIMES.get(name)
    if not config:
        return RuntimeInfo(
            name=name,
            display_name=name,
            command=name,
            available=False,
            path=None,
            capabilities="Unknown runtime",
            mcp_add_command=None,
        )
    
    # Custom is "supported", but not auto-detectable as installed (user provides the actual command line).
    if name == "custom":
        return RuntimeInfo(
            name=name,
            display_name=config["display_name"],
            command=config["command"],
            available=False,
            path=None,
            capabilities=config["capabilities"],
            mcp_add_command=None,
        )

    command = config["command"]
    detected_command = resolve_runtime_executable(name)
    path = find_subprocess_executable(detected_command)
    available = path is not None
    
    mcp_add_command = None
    if config.get("mcp_add_pattern") and available:
        # Parse the pattern into a command list
        # This is just for reference; actual execution happens elsewhere
        mcp_add_command = config["mcp_add_pattern"].split()
    
    return RuntimeInfo(
        name=name,
        display_name=config["display_name"],
        command=detected_command if available else command,
        available=available,
        path=path,
        capabilities=config["capabilities"],
        mcp_add_command=mcp_add_command,
    )


def detect_all_runtimes(primary_only: bool = True) -> List[RuntimeInfo]:
    """Detect all known runtimes on the system.
    
    Args:
        primary_only: If True, only check first-class runtimes (claude, codex, droid, amp, auggie, neovate, gemini, kimi).
                     If False, check all configured runtimes (including custom).
    
    Returns:
        List of RuntimeInfo for each runtime.
    """
    names = PRIMARY_RUNTIMES if primary_only else list(KNOWN_RUNTIMES.keys())
    return [detect_runtime(name) for name in names]


def get_available_runtimes(primary_only: bool = True) -> List[RuntimeInfo]:
    """Get only the runtimes that are available on the system."""
    return [r for r in detect_all_runtimes(primary_only) if r.available]


def get_runtime_command(name: str) -> List[str]:
    """Get the default command for a runtime.
    
    Returns the command as a list suitable for subprocess.
    """
    if name == "custom":
        return []
    config = KNOWN_RUNTIMES.get(name)
    if not config:
        return [name]
    return [resolve_runtime_executable(name)]


def get_cccc_mcp_stdio_command() -> List[str]:
    """Return the most stable command line for launching `cccc mcp`.

    Prefer an absolute path to the installed `cccc` entrypoint when available.
    On Windows this avoids relying on runtime-specific PATH inheritance for MCP
    child processes. Fall back to the current Python interpreter otherwise.
    
    Priority:
    1. Check sibling directory of sys.executable for cccc/cccc.exe
    2. Use shutil.which to find cccc in PATH
    3. Fall back to python -m cccc.ports.mcp.main
    """
    candidates: List[Path] = []
    is_windows = sys.platform.startswith("win")
    try:
        bin_dir = Path(sys.executable).resolve().parent
        names = ["cccc.exe", "cccc.cmd", "cccc.bat", "cccc", "cccc-script.py"] if is_windows else ["cccc"]
        for name in names:
            candidate = bin_dir / name
            if candidate.exists():
                candidates.append(candidate)
    except Exception:
        pass
    for raw in (shutil.which("cccc"), shutil.which("cccc.exe") if is_windows else None):
        if raw:
            candidates.append(Path(raw))
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except Exception:
            resolved = str(candidate)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        return [resolved, "mcp"]
    return [sys.executable, "-m", "cccc.ports.mcp.main"]


def get_runtime_command_with_flags(name: str) -> List[str]:
    """Get the command with recommended flags for autonomous operation."""
    commands = {
        "amp": ["amp"],
        "auggie": ["auggie"],
        "claude": ["claude", "--dangerously-skip-permissions"],
        # Codex spawns MCP servers as subprocesses; ensure it inherits actor env (CCCC_GROUP_ID/CCCC_ACTOR_ID)
        # so MCP tools can resolve "self" context reliably.
        "codex": ["codex", "-c", "shell_environment_policy.inherit=all", "--dangerously-bypass-approvals-and-sandbox", "--search"],
        "droid": ["droid", "--auto", "high"],
        "gemini": _gemini_command_with_flags(),
        "kimi": ["kimi", "--yolo"],
        "neovate": ["neovate"],
        "custom": [],
    }
    return commands.get(name, [name])
