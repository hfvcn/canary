"""SerenaAdapter — OneShot implementation of SemanticProvider using Serena.

Calls Serena via subprocess (uv run) because Ralph and Serena have separate
Python environments. Each query spawns a small Python script in Serena's venv.
Falls back gracefully if Serena directory or uv is not available.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import List, Optional

from .semantic_provider import Confidence, SymbolReference

logger = logging.getLogger(__name__)

_SERENA_DIR_NAME = "ralph/serena_ralph"
_QUERY_TIMEOUT = 30  # seconds per subprocess call


class SerenaAdapter:
    """OneShot Serena adapter — calls Serena tools via subprocess.

    Initialization starts the Serena agent + LSP once (_ensure_init),
    then each query reuses that running process via a single long-lived
    subprocess that accepts JSON-line queries on stdin.

    If Serena is not available, all methods return graceful defaults (None/[]).
    """

    def __init__(self, project_root: str | Path) -> None:
        self._project_root = Path(project_root).resolve()
        self._serena_dir = self._project_root / _SERENA_DIR_NAME
        self._initialized = False
        self._available = False
        self._proc: subprocess.Popen | None = None

    def _ensure_init(self) -> bool:
        """Lazy-start the Serena bridge subprocess. Returns True if ready."""
        if self._initialized:
            return self._available
        self._initialized = True

        if not self._serena_dir.is_dir():
            logger.info("Serena directory not found at %s", self._serena_dir)
            return False

        try:
            self._proc = subprocess.Popen(
                ["uv", "run", "python", "-c", _BRIDGE_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self._serena_dir),
                text=True,
                env={
                    **__import__("os").environ,
                    "SERENA_PROJECT_ROOT": str(self._project_root),
                },
            )
            # Wait for ready signal
            ready_line = self._proc.stdout.readline().strip()
            if ready_line == "READY":
                self._available = True
                logger.info("Serena bridge ready")
            else:
                logger.warning("Serena bridge failed to start: %s", ready_line)
                self._cleanup()
        except FileNotFoundError:
            logger.info("uv not found — Serena unavailable")
        except Exception as e:
            logger.warning("Failed to start Serena bridge: %s", e)
            self._cleanup()

        return self._available

    def _query(self, method: str, **kwargs) -> Optional[str]:
        """Send a query to the bridge and return the JSON response string."""
        if not self._ensure_init() or self._proc is None:
            return None
        try:
            request = json.dumps({"method": method, **kwargs})
            self._proc.stdin.write(request + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            if not line:
                logger.warning("Serena bridge closed unexpectedly")
                self._cleanup()
                return None
            return line.strip()
        except Exception as e:
            logger.debug("Serena query %s failed: %s", method, e)
            self._cleanup()
            return None

    def _cleanup(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
            self._available = False

    def close(self) -> None:
        """Shut down the bridge subprocess."""
        if self._proc is not None:
            try:
                self._proc.stdin.write('{"method":"quit"}\n')
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                self._cleanup()

    def __del__(self) -> None:
        self.close()

    # -- SemanticProvider interface --

    def symbol_exists(self, path: str, name_path: str) -> Optional[bool]:
        raw = self._query("find_symbol", path=path, name_path=name_path)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            if data is None:
                return None
            return len(data) > 0
        except (json.JSONDecodeError, TypeError):
            return None

    def find_references(self, path: str, name_path: str) -> List[SymbolReference]:
        raw = self._query("find_references", path=path, name_path=name_path)
        if raw is None:
            return []
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            refs = []
            for item in data:
                refs.append(SymbolReference(
                    ref_path=item.get("ref_path", ""),
                    ref_symbol=item.get("ref_symbol", ""),
                    confidence=item.get("confidence", "exact"),
                ))
            return refs
        except (json.JSONDecodeError, TypeError):
            return []

    def get_public_symbols(self, path: str) -> List[str]:
        raw = self._query("get_public_symbols", path=path)
        if raw is None:
            return []
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [s for s in data if isinstance(s, str)]
        except (json.JSONDecodeError, TypeError):
            return []


# ---------------------------------------------------------------------------
# Bridge script — runs inside Serena's venv via `uv run python -c`
# ---------------------------------------------------------------------------

_BRIDGE_SCRIPT = r'''
import json, os, sys

project_root = os.environ["SERENA_PROJECT_ROOT"]

try:
    from serena.config.serena_config import SerenaConfig
    from serena.agent import SerenaAgent
    from serena.tools.symbol_tools import (
        FindSymbolTool,
        FindReferencingSymbolsTool,
        GetSymbolsOverviewTool,
    )

    config = SerenaConfig()
    config.web_dashboard = False
    config.web_dashboard_open_on_launch = False
    agent = SerenaAgent(project=project_root, serena_config=config)
    proj = agent.get_active_project()
    proj.create_language_server_manager()

    find_tool = agent.get_tool(FindSymbolTool)
    ref_tool = agent.get_tool(FindReferencingSymbolsTool)
    overview_tool = agent.get_tool(GetSymbolsOverviewTool)

    print("READY", flush=True)
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    sys.exit(1)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        print("null", flush=True)
        continue

    method = req.get("method", "")

    if method == "quit":
        break

    try:
        if method == "find_symbol":
            raw = find_tool.apply(
                req["name_path"],
                relative_path=req.get("path", ""),
                include_body=False,
            )
            # raw is a JSON string from Serena
            data = json.loads(raw)
            print(json.dumps(data), flush=True)

        elif method == "find_references":
            raw = ref_tool.apply(
                req["name_path"],
                relative_path=req.get("path", ""),
            )
            # Parse Serena's nested JSON output into flat ref list
            data = json.loads(raw)
            refs = []
            if isinstance(data, dict):
                for file_path, symbols in data.items():
                    if isinstance(symbols, dict):
                        for kind, entries in symbols.items():
                            if isinstance(entries, list):
                                for entry in entries:
                                    refs.append({
                                        "ref_path": file_path,
                                        "ref_symbol": entry.get("name_path", ""),
                                        "confidence": "exact",
                                    })
                            elif isinstance(entries, dict):
                                refs.append({
                                    "ref_path": file_path,
                                    "ref_symbol": entries.get("name_path", ""),
                                    "confidence": "exact",
                                })
            print(json.dumps(refs), flush=True)

        elif method == "get_public_symbols":
            raw = overview_tool.apply(req["path"])
            data = json.loads(raw)
            symbols = []
            if isinstance(data, dict):
                for kind, names in data.items():
                    if isinstance(names, list):
                        symbols.extend(n for n in names if isinstance(n, str) and not n.startswith("_"))
                    elif isinstance(names, str) and not names.startswith("_"):
                        symbols.append(names)
            print(json.dumps(symbols), flush=True)

        else:
            print("null", flush=True)

    except Exception as e:
        print("null", flush=True)

# Cleanup
try:
    proj.shutdown()
except Exception:
    pass
'''
