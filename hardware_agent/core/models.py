"""Core data models for hardware-agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class OS(Enum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


@dataclass
class Environment:
    os: OS
    os_version: str
    python_version: str
    python_path: str
    pip_path: str
    env_type: str  # "system", "venv", "conda"
    env_path: Optional[str]
    name: str
    installed_packages: dict[str, str] = field(default_factory=dict)
    usb_devices: list[str] = field(default_factory=list)
    visa_resources: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    id: str
    name: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    output: str = ""
    error: str = ""
    is_terminal: bool = False


@dataclass
class Iteration:
    number: int
    timestamp: datetime
    tool_call: ToolCall
    result: ToolResult
    duration_ms: int = 0


@dataclass
class AgentContext:
    session_id: str
    device_type: str
    device_name: str
    device_hints: dict[str, Any]
    environment: Environment
    iterations: list[Iteration] = field(default_factory=list)
    max_iterations: int = 20

    def format_history_for_llm(self) -> list[dict]:
        """Return tool_use/tool_result message pairs for Anthropic API."""
        messages = []
        for it in self.iterations:
            messages.append({
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": it.tool_call.id,
                    "name": it.tool_call.name,
                    "input": it.tool_call.parameters,
                }],
            })
            output = it.result.stdout or it.result.output
            if it.result.stderr:
                output += f"\n[stderr]: {it.result.stderr}"
            if it.result.error:
                output += f"\n[error]: {it.result.error}"
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": it.tool_call.id,
                    "content": output or "(no output)",
                    "is_error": not it.result.success,
                }],
            })
        return messages

    def get_current_iteration(self) -> int:
        return len(self.iterations)


@dataclass
class SessionResult:
    success: bool
    session_id: str
    iterations: int
    duration_seconds: float
    output_file: Optional[str] = None
    final_code: Optional[str] = None
    error_message: Optional[str] = None
