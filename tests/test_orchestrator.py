"""Tests for hardware_agent.core.orchestrator — Orchestrator.run()."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from hardware_agent.core.models import (
    OS,
    AgentContext,
    Environment,
    Iteration,
    SessionResult,
    ToolCall,
    ToolResult,
)
from hardware_agent.core.orchestrator import Orchestrator
from hardware_agent.devices.base import DeviceHints, DeviceInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device_module():
    """Create a fully-mocked DeviceModule."""
    dm = MagicMock()
    dm.get_info.return_value = DeviceInfo(
        identifier="rigol_ds1054z",
        name="Rigol DS1054Z",
        manufacturer="Rigol",
        category="oscilloscope",
        model_patterns=["DS1054Z"],
        connection_type="USB-TMC",
    )
    dm.get_hints.return_value = DeviceHints(
        common_errors={"No backend available": "Install pyvisa-py"},
        setup_steps=["Install pyvisa", "Fix permissions"],
        os_specific={},
        known_quirks=[],
        required_packages=["pyvisa", "pyvisa-py"],
    )
    dm.verify_connection.return_value = (True, "RIGOL,DS1054Z,serial,ver")
    dm.generate_example_code.return_value = "import pyvisa"
    return dm


def _make_environment():
    return Environment(
        os=OS.LINUX,
        os_version="Ubuntu 24.04",
        python_version="3.12.0",
        python_path="/usr/bin/python3",
        pip_path="/usr/bin/pip3",
        env_type="venv",
        env_path="/home/user/venv",
        name="venv",
        installed_packages={"pip": "24.0"},
        usb_devices=["Bus 001 Device 003: Rigol"],
        visa_resources=[],
    )


def _make_tool_call(name, params=None):
    return ToolCall(
        id=f"toolu_{name}_001",
        name=name,
        parameters=params or {},
    )


def _make_tool_result(success=True, stdout="", stderr="", error="", is_terminal=False, output=""):
    return ToolResult(
        success=success,
        stdout=stdout,
        stderr=stderr,
        error=error,
        is_terminal=is_terminal,
        output=output,
    )


# ---------------------------------------------------------------------------
# Full successful run
# ---------------------------------------------------------------------------

class TestOrchestratorSuccessfulRun:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_scripted_sequence_to_success(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        # -- Setup mocks --
        env = _make_environment()
        dm = _make_device_module()

        # LLM returns a scripted sequence of tool calls
        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("check_installed", {"package": "pyvisa"}),
            _make_tool_call("pip_install", {"packages": ["pyvisa", "pyvisa-py"]}),
            _make_tool_call("list_usb_devices", {}),
            _make_tool_call("check_device", {}),
            _make_tool_call("complete", {"code": "import pyvisa", "summary": "done"}),
        ]

        # Executor returns matching results
        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(success=False, stdout="pyvisa is NOT installed"),
            _make_tool_result(success=True, stdout="Successfully installed pyvisa"),
            _make_tool_result(success=True, stdout="Bus 001 Device 003: Rigol"),
            _make_tool_result(success=True, stdout="RIGOL,DS1054Z"),
            _make_tool_result(success=True, stdout="import pyvisa", output="done", is_terminal=True),
        ]

        # Store and community are no-ops
        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        # -- Run orchestrator --
        orch = Orchestrator(
            environment=env,
            device_module=dm,
            auto_confirm=True,
            max_iterations=20,
        )

        result = orch.run()

        # -- Assertions --
        assert isinstance(result, SessionResult)
        assert result.success is True
        assert result.iterations == 5
        assert result.final_code == "import pyvisa"
        assert result.error_message is None

        # LLM was called 5 times
        assert mock_llm.get_next_action.call_count == 5

        # Executor was called 5 times
        assert mock_executor.execute.call_count == 5

        # Session was completed in the store
        mock_store.complete_session.assert_called_once()

    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_iterations_are_logged(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("bash", {"command": "echo hello"}),
            _make_tool_call("complete", {"code": "pass"}),
        ]

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(success=True, stdout="hello"),
            _make_tool_result(success=True, stdout="pass", is_terminal=True),
        ]

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        orch = Orchestrator(
            environment=env, device_module=dm, auto_confirm=True, max_iterations=20,
        )
        result = orch.run()

        assert result.success is True
        # log_iteration should be called once per iteration (2 total)
        assert mock_store.log_iteration.call_count == 2


# ---------------------------------------------------------------------------
# Max iterations reached -> failure result
# ---------------------------------------------------------------------------

class TestOrchestratorMaxIterations:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_max_iterations_produces_failure(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()
        max_iter = 3

        # LLM always returns a non-terminal tool call
        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.return_value = _make_tool_call(
            "bash", {"command": "lsusb"}
        )

        # Executor always returns a non-terminal result
        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.return_value = _make_tool_result(
            success=True, stdout="Bus 001"
        )

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        orch = Orchestrator(
            environment=env, device_module=dm, auto_confirm=True,
            max_iterations=max_iter,
        )
        result = orch.run()

        assert result.success is False
        assert result.iterations == max_iter
        assert "Max iterations" in result.error_message

        # LLM was called exactly max_iter times
        assert mock_llm.get_next_action.call_count == max_iter


# ---------------------------------------------------------------------------
# give_up tool -> failure result
# ---------------------------------------------------------------------------

class TestOrchestratorGiveUp:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_give_up_produces_failure(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("check_device", {}),
            _make_tool_call("give_up", {
                "reason": "Device not responding",
                "suggestions": ["Check cable"],
            }),
        ]

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(
                success=False, error="No VISA resources found"
            ),
            _make_tool_result(
                success=False,
                error="Device not responding",
                output="Reason: Device not responding\n\nSuggestions:\n  - Check cable\n",
                is_terminal=True,
            ),
        ]

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        orch = Orchestrator(
            environment=env, device_module=dm, auto_confirm=True, max_iterations=20,
        )
        result = orch.run()

        assert result.success is False
        assert "Device not responding" in result.error_message
        assert result.iterations == 2


# ---------------------------------------------------------------------------
# LLM error -> failure result
# ---------------------------------------------------------------------------

class TestOrchestratorLLMError:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_llm_exception_produces_failure(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = RuntimeError("API rate limited")

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        mock_executor = MockToolExecutor.return_value

        orch = Orchestrator(
            environment=env, device_module=dm, auto_confirm=True, max_iterations=20,
        )
        result = orch.run()

        assert result.success is False
        assert "LLM error" in result.error_message
        assert "API rate limited" in result.error_message
        assert result.iterations == 0
        # Executor should never have been called
        mock_executor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Loop detection integration
# ---------------------------------------------------------------------------

class TestOrchestratorLoopDetection:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_loop_breaker_passed_to_llm(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        """When the same tool fails repeatedly, a loop_breaker should be passed."""
        env = _make_environment()
        dm = _make_device_module()

        same_call = _make_tool_call("bash", {"command": "lsusb"})
        fail_result = _make_tool_result(
            success=False, stderr="permission denied"
        )

        call_count = [0]

        def llm_side_effect(context, community_data=None, loop_breaker=None):
            call_count[0] += 1
            if call_count[0] <= 3:
                return same_call
            # After loop detection, give up
            return _make_tool_call("complete", {"code": "done"})

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = llm_side_effect

        exec_count = [0]

        def exec_side_effect(tool_call):
            exec_count[0] += 1
            if tool_call.name == "complete":
                return _make_tool_result(
                    success=True, stdout="done", is_terminal=True
                )
            return fail_result

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = exec_side_effect

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        mock_replay.find_replay_candidate.return_value = None

        orch = Orchestrator(
            environment=env, device_module=dm, auto_confirm=True, max_iterations=20,
        )
        result = orch.run()

        assert result.success is True

        # After the second identical failure, loop_breaker should be set.
        # The 3rd call to get_next_action should have received a loop_breaker.
        # (1st fail: no loop, 2nd fail: loop detected, 3rd call receives breaker)
        calls = mock_llm.get_next_action.call_args_list
        # The third call (index 2) should have loop_breaker=None still
        # (loop detected *after* the 2nd execution, so the 3rd LLM call gets the breaker)
        third_call_kwargs = calls[2]
        # calls[2] is either positional or keyword — check for loop_breaker
        # The orchestrator passes loop_breaker as positional arg #3 or keyword
        if len(third_call_kwargs[0]) >= 3:
            assert third_call_kwargs[0][2] is not None  # loop_breaker set
        elif "loop_breaker" in third_call_kwargs[1]:
            assert third_call_kwargs[1]["loop_breaker"] is not None


# ---------------------------------------------------------------------------
# Troubleshoot mode
# ---------------------------------------------------------------------------

class TestOrchestratorTroubleshootMode:
    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_troubleshoot_mode_skips_replay(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("complete", {"code": "fixed"}),
        ]

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(success=True, stdout="fixed", is_terminal=True),
        ]

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value
        # Even if a candidate exists, it should NOT be used
        mock_replay.find_replay_candidate.return_value = {
            "success_count": 5, "steps": []
        }

        orch = Orchestrator(
            environment=env,
            device_module=dm,
            auto_confirm=True,
            max_iterations=20,
            mode="troubleshoot",
        )
        result = orch.run()

        assert result.success is True
        # find_replay_candidate should not have been called
        mock_replay.find_replay_candidate.assert_not_called()

    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_troubleshoot_mode_with_null_device(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        from hardware_agent.devices.null_device import NullDeviceModule

        env = _make_environment()
        dm = NullDeviceModule()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("complete", {"code": "# solution", "summary": "Fixed it"}),
        ]

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(success=True, stdout="# solution", is_terminal=True),
        ]

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value

        orch = Orchestrator(
            environment=env,
            device_module=dm,
            auto_confirm=True,
            max_iterations=20,
            mode="troubleshoot",
        )
        result = orch.run()

        assert result.success is True
        assert result.final_code == "# solution"

    @patch("hardware_agent.core.orchestrator.analyze_session", return_value=None)
    @patch("hardware_agent.core.orchestrator.fingerprint_initial_state", return_value="fp123")
    @patch("hardware_agent.core.orchestrator.ReplayEngine")
    @patch("hardware_agent.core.orchestrator.CommunityKnowledge")
    @patch("hardware_agent.core.orchestrator.DataStore")
    @patch("hardware_agent.core.orchestrator.ToolExecutor")
    @patch("hardware_agent.core.orchestrator.LLMClient")
    def test_troubleshoot_uses_troubleshoot_tools(
        self,
        MockLLMClient,
        MockToolExecutor,
        MockDataStore,
        MockCommunity,
        MockReplay,
        mock_fingerprint,
        mock_analyze,
    ):
        env = _make_environment()
        dm = _make_device_module()

        mock_llm = MockLLMClient.return_value
        mock_llm.get_next_action.side_effect = [
            _make_tool_call("web_search", {"query": "pyvisa error"}),
            _make_tool_call("complete", {"code": "# fix"}),
        ]

        mock_executor = MockToolExecutor.return_value
        mock_executor.execute.side_effect = [
            _make_tool_result(success=True, stdout="1. Fix found"),
            _make_tool_result(success=True, stdout="# fix", is_terminal=True),
        ]

        mock_store = MockDataStore.return_value
        mock_store.create_session.return_value = None
        mock_store.log_iteration.return_value = None
        mock_store.complete_session.return_value = None
        mock_store.save_analysis.return_value = None

        mock_community = MockCommunity.return_value
        mock_community.is_enabled.return_value = False
        mock_community.flush_queue.return_value = None

        mock_replay = MockReplay.return_value

        orch = Orchestrator(
            environment=env,
            device_module=dm,
            auto_confirm=True,
            max_iterations=20,
            mode="troubleshoot",
        )
        result = orch.run()

        assert result.success is True
        # The LLM context should have mode="troubleshoot"
        llm_calls = mock_llm.get_next_action.call_args_list
        first_call_context = llm_calls[0][0][0]
        assert first_call_context.mode == "troubleshoot"
