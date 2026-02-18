"""Shared test fixtures for hardware-agent tests."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hardware_agent.core.models import (
    OS,
    AgentContext,
    Environment,
    Iteration,
    ToolCall,
    ToolResult,
)
from hardware_agent.data.store import DataStore
from hardware_agent.devices.rigol_ds1054z.module import RigolDS1054ZModule


@pytest.fixture
def mock_environment() -> Environment:
    """Pre-built Environment with known values."""
    return Environment(
        os=OS.LINUX,
        os_version="Ubuntu 24.04",
        python_version="3.12.0",
        python_path="/usr/bin/python3",
        pip_path="/usr/bin/pip3",
        env_type="venv",
        env_path="/home/user/project/venv",
        name="venv",
        installed_packages={
            "pip": "24.0",
            "setuptools": "69.0",
        },
        usb_devices=[
            "Bus 001 Device 003: ID 1ab1:04ce Rigol Technologies DS1054Z",
        ],
        visa_resources=[],
    )


@pytest.fixture
def mock_environment_empty() -> Environment:
    """Environment with no packages or devices."""
    return Environment(
        os=OS.LINUX,
        os_version="Ubuntu 24.04",
        python_version="3.12.0",
        python_path="/usr/bin/python3",
        pip_path="/usr/bin/pip3",
        env_type="system",
        env_path=None,
        name="system",
        installed_packages={},
        usb_devices=[],
        visa_resources=[],
    )


@pytest.fixture
def mock_rigol_module() -> RigolDS1054ZModule:
    """RigolDS1054ZModule instance."""
    return RigolDS1054ZModule()


@pytest.fixture
def temp_db(tmp_path):
    """DataStore with a temporary SQLite database."""
    db_path = str(tmp_path / "test.db")
    store = DataStore(db_path=db_path)
    yield store
    store.close()


@pytest.fixture
def mock_agent_context(mock_environment) -> AgentContext:
    """Pre-built AgentContext."""
    return AgentContext(
        session_id="test-session-123",
        device_type="rigol_ds1054z",
        device_name="Rigol DS1054Z",
        device_hints={
            "common_errors": {
                "No backend available": "Install pyvisa-py",
            },
            "setup_steps": ["Install pyvisa", "Fix permissions"],
            "os_specific": {},
            "known_quirks": ["USB 3.0 may cause issues"],
            "required_packages": ["pyvisa", "pyvisa-py", "pyusb"],
        },
        environment=mock_environment,
        max_iterations=20,
    )


def mock_llm_response(tool_name: str, params: dict[str, Any]) -> MagicMock:
    """Create a mock Anthropic API response with a tool_use block."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = f"toolu_{tool_name}_001"
    tool_block.name = tool_name
    tool_block.input = params

    response = MagicMock()
    response.content = [tool_block]
    return response


def make_iteration(
    number: int,
    tool_name: str,
    params: dict | None = None,
    success: bool = True,
    stdout: str = "",
    stderr: str = "",
    error: str = "",
    is_terminal: bool = False,
) -> Iteration:
    """Helper to create an Iteration for testing."""
    return Iteration(
        number=number,
        timestamp=datetime.now(),
        tool_call=ToolCall(
            id=f"tool_{number}",
            name=tool_name,
            parameters=params or {},
        ),
        result=ToolResult(
            success=success,
            stdout=stdout,
            stderr=stderr,
            error=error,
            is_terminal=is_terminal,
        ),
        duration_ms=100,
    )
