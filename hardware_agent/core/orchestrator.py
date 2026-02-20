"""Orchestrator — the main agent loop."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from hardware_agent.core.executor import ToolExecutor
from hardware_agent.core.llm import LLMClient
from hardware_agent.core.loop_detector import LoopDetector
from hardware_agent.core.models import (
    AgentContext,
    Environment,
    Iteration,
    SessionResult,
    ToolCall,
)
from hardware_agent.data.analysis import analyze_session
from hardware_agent.data.community import CommunityKnowledge
from hardware_agent.data.fingerprint import fingerprint_initial_state
from hardware_agent.data.replay import ReplayEngine
from hardware_agent.data.store import DataStore
from hardware_agent.devices.base import DeviceModule


class Orchestrator:
    """Runs the main agent loop: detect → replay → LLM loop → analyze → share."""

    def __init__(
        self,
        environment: Environment,
        device_module: DeviceModule,
        auto_confirm: bool = False,
        console: Optional[Console] = None,
        max_iterations: int = 20,
        model: str = "claude-sonnet-4-20250514",
        mode: str = "connect",
    ):
        self.environment = environment
        self.device_module = device_module
        self.auto_confirm = auto_confirm
        self.console = console or Console()
        self.max_iterations = max_iterations
        self.mode = mode

        self.confirm_callback: Callable[[str], bool]
        if auto_confirm:
            self.confirm_callback = lambda _: True
        else:
            self.confirm_callback = self._interactive_confirm

        self.llm = LLMClient(model=model)
        self.executor = ToolExecutor(
            environment,
            device_module,
            self.confirm_callback,
            ask_user_callback=self._interactive_ask_user,
        )
        self.loop_detector = LoopDetector()
        self.store = DataStore()
        self.community = CommunityKnowledge(store=self.store)
        self.replay_engine = ReplayEngine()

    def run(self) -> SessionResult:
        """Execute the full agent session."""
        start_time = time.time()

        # 1. SETUP
        session_id = str(uuid.uuid4())
        device_info = self.device_module.get_info()
        device_hints = self.device_module.get_hints(self.environment.os.value)
        fingerprint = fingerprint_initial_state(
            self.environment, device_info.identifier
        )

        # Convert hints to dict for context
        hints_dict = {
            "common_errors": device_hints.common_errors,
            "setup_steps": device_hints.setup_steps,
            "os_specific": device_hints.os_specific,
            "documentation_urls": device_hints.documentation_urls,
            "known_quirks": device_hints.known_quirks,
            "required_packages": device_hints.required_packages,
        }

        context = AgentContext(
            session_id=session_id,
            device_type=device_info.identifier,
            device_name=device_info.name,
            device_hints=hints_dict,
            environment=self.environment,
            max_iterations=self.max_iterations,
            mode=self.mode,
        )

        self.store.create_session(
            session_id=session_id,
            device_type=device_info.identifier,
            device_name=device_info.name,
            os_name=self.environment.os.value,
            os_version=self.environment.os_version,
            python_version=self.environment.python_version,
            env_type=self.environment.env_type,
            fingerprint=fingerprint,
        )

        if self.mode == "troubleshoot":
            panel_title = "Troubleshoot Session"
        else:
            panel_title = "Hardware Agent Session"
        self.console.print(
            Panel(
                f"[bold]Device:[/] {device_info.name}\n"
                f"[bold]Type:[/] {device_info.connection_type}\n"
                f"[bold]OS:[/] {self.environment.os.value} "
                f"({self.environment.os_version})\n"
                f"[bold]Python:[/] {self.environment.python_version}",
                title=panel_title,
                border_style="blue",
            )
        )

        # 2. PULL COMMUNITY KNOWLEDGE
        self.community.flush_queue()
        community_data = None
        if self.community.is_enabled():
            community_data = self.community.pull_patterns(
                device_info.identifier, self.environment.os.value
            )

        # 3. TRY REPLAY (skip in troubleshoot mode — always interactive)
        candidate = None
        if self.mode != "troubleshoot":
            candidate = self.replay_engine.find_replay_candidate(
                device_info.identifier,
                self.environment.os.value,
                fingerprint,
                self.store,
            )
        if candidate:
            count = candidate.get("success_count", 0)
            self.console.print(
                f"\n[green]Found a proven setup sequence "
                f"({count} successful connections). Running directly...[/]\n"
            )
            replay_result = self.replay_engine.execute_replay(
                candidate,
                self.executor,
                self.device_module,
                self.environment.os.value,
                self.confirm_callback,
            )
            if replay_result["success"]:
                duration = time.time() - start_time
                result = SessionResult(
                    success=True,
                    session_id=session_id,
                    iterations=replay_result.get("steps_executed", 0),
                    duration_seconds=duration,
                    summary="Replayed proven setup sequence successfully.",
                )
                self._push_contribution(
                    session_id, context, "success", fingerprint
                )
                self.store.complete_session(session_id, result)
                return result
            else:
                self.console.print(
                    f"[yellow]Replay failed at step "
                    f"{replay_result.get('failed_at_step', '?')}. "
                    f"Falling back to AI agent...[/]\n"
                )

        # 4. LLM AGENT LOOP
        result: Optional[SessionResult] = None
        loop_breaker: Optional[str] = None

        while context.get_current_iteration() < self.max_iterations:
            iteration_num = context.get_current_iteration() + 1
            self.console.print(
                f"\n[dim]─── Iteration {iteration_num}/{self.max_iterations} "
                f"───[/]"
            )

            try:
                tool_call = self.llm.get_next_action(
                    context, community_data, loop_breaker
                )
            except Exception as e:
                self.console.print(f"[red]LLM error: {e}[/]")
                result = SessionResult(
                    success=False,
                    session_id=session_id,
                    iterations=context.get_current_iteration(),
                    duration_seconds=time.time() - start_time,
                    error_message=f"LLM error: {e}",
                )
                break

            loop_breaker = None

            # Display what we're doing
            self._display_tool_call(tool_call)

            # Execute
            iter_start = time.time()
            tool_result = self.executor.execute(tool_call)
            iter_duration_ms = int((time.time() - iter_start) * 1000)

            # Display result
            self._display_result(tool_result)

            # Record iteration
            iteration = Iteration(
                number=iteration_num,
                timestamp=datetime.now(),
                tool_call=tool_call,
                result=tool_result,
                duration_ms=iter_duration_ms,
            )
            self.store.log_iteration(session_id, iteration)
            context.iterations.append(iteration)

            # Check if done
            if tool_result.is_terminal:
                duration = time.time() - start_time
                if tool_result.success:
                    result = SessionResult(
                        success=True,
                        session_id=session_id,
                        iterations=context.get_current_iteration(),
                        duration_seconds=duration,
                        summary=tool_call.parameters.get("summary", ""),
                    )
                else:
                    result = SessionResult(
                        success=False,
                        session_id=session_id,
                        iterations=context.get_current_iteration(),
                        duration_seconds=duration,
                        error_message=tool_result.error,
                    )
                break

            # Check for loops
            loop_warning = self.loop_detector.check(tool_call, tool_result)
            if loop_warning.is_loop:
                self.console.print(
                    f"[yellow]Loop detected: {loop_warning.message}[/]"
                )
                loop_breaker = self.loop_detector.get_loop_breaker_message()

        # Max iterations
        if result is None:
            duration = time.time() - start_time
            result = SessionResult(
                success=False,
                session_id=session_id,
                iterations=context.get_current_iteration(),
                duration_seconds=duration,
                error_message="Max iterations reached",
            )

        # 5. POST-SESSION ANALYSIS
        try:
            analyzed = analyze_session(
                context.iterations,
                device_type=context.device_type,
                os_name=context.environment.os.value,
                fingerprint=fingerprint,
                outcome="success" if result.success else "failed",
            )
            # Store analysis results locally
            if analyzed:
                self.store.save_analysis(session_id, analyzed)
        except Exception:
            pass  # Analysis is best-effort

        # 6. PUSH TO SUPABASE
        self._push_contribution(
            session_id,
            context,
            "success" if result.success else "failed",
            fingerprint,
        )

        # 7. COMPLETE SESSION
        self.store.complete_session(session_id, result)

        # Display final result
        self._display_final_result(result)

        return result

    def _push_contribution(
        self,
        session_id: str,
        context: AgentContext,
        outcome: str,
        fingerprint: str,
    ) -> None:
        """Push anonymized contribution to Supabase (best-effort)."""
        if not self.community.is_enabled():
            return
        try:
            from hardware_agent.data.analysis import normalize_iterations

            steps = normalize_iterations(context.iterations)
            self.community.push_contribution({
                "device_type": context.device_type,
                "os": context.environment.os.value,
                "success": outcome == "success",
                "steps": steps,
                "os_version": context.environment.os_version,
                "initial_state_fingerprint": fingerprint,
                "outcome": outcome,
                "total_steps": len(context.iterations),
                "agent_version": "0.1.0",
            })
        except Exception:
            pass  # Best-effort

    def _display_tool_call(self, tool_call: ToolCall) -> None:
        """Display the tool call being executed."""
        name = tool_call.name
        params = tool_call.parameters

        if name == "bash":
            self.console.print(f"[bold cyan]$ {params.get('command', '')}[/]")
        elif name == "pip_install":
            pkgs = ", ".join(params.get("packages", []))
            self.console.print(f"[bold cyan]pip install {pkgs}[/]")
        elif name == "run_python":
            code = params.get("code", "")
            if len(code) > 200:
                code = code[:200] + "..."
            self.console.print("[bold cyan]Running Python code:[/]")
            self.console.print(Syntax(code, "python", theme="monokai"))
        elif name == "ask_user":
            self.console.print(
                f"[bold yellow]Agent asks:[/] {params.get('question', '')}"
            )
        elif name == "check_device":
            self.console.print("[bold cyan]Checking device connection...[/]")
        elif name == "complete":
            self.console.print("[bold green]Connection successful![/]")
        elif name == "give_up":
            self.console.print("[bold red]Agent giving up.[/]")
        elif name == "web_search":
            self.console.print(
                f"[bold cyan]Searching: {params.get('query', '')}[/]"
            )
        elif name == "web_fetch":
            self.console.print(
                f"[bold cyan]Reading: {params.get('url', '')}[/]"
            )
        elif name == "run_user_script":
            self.console.print(
                f"[bold cyan]Running user script: {params.get('path', '')}[/]"
            )
        else:
            self.console.print(f"[bold cyan]{name}[/] {params}")

    def _display_result(self, result: ToolResult) -> None:
        """Display the result of a tool execution."""
        if result.success:
            if result.stdout:
                output = result.stdout
                if len(output) > 500:
                    output = output[:500] + "\n... (truncated)"
                self.console.print(f"[green]{output}[/]")
        else:
            error = result.error or result.stderr
            if error:
                if len(error) > 500:
                    error = error[:500] + "\n... (truncated)"
                self.console.print(f"[red]{error}[/]")

    def _display_final_result(self, result: SessionResult) -> None:
        """Display the final session result."""
        self.console.print()
        if self.mode == "troubleshoot":
            success_msg = "Issue resolved!"
        else:
            success_msg = "Connection established!"
        if result.success:
            self.console.print(
                Panel(
                    f"[bold green]{success_msg}[/]\n"
                    f"Iterations: {result.iterations}\n"
                    f"Duration: {result.duration_seconds:.1f}s",
                    title="Session Complete",
                    border_style="green",
                )
            )
            if result.summary:
                self.console.print(f"\n[bold]Summary:[/] {result.summary}")
        else:
            self.console.print(
                Panel(
                    f"[bold red]Connection failed[/]\n"
                    f"Iterations: {result.iterations}\n"
                    f"Duration: {result.duration_seconds:.1f}s\n"
                    f"Error: {result.error_message}",
                    title="Session Failed",
                    border_style="red",
                )
            )

    def _interactive_ask_user(
        self, question: str, choices: list[str] | None = None
    ) -> str:
        """Prompt the user with a question, optionally with numbered choices."""
        from rich.prompt import Prompt

        self.console.print()
        if choices:
            self.console.print(f"[bold yellow]{question}[/]")
            for i, choice in enumerate(choices, 1):
                self.console.print(f"  [cyan]{i}.[/] {choice}")
            answer = Prompt.ask(
                "Enter your choice (number or text)",
                console=self.console,
            )
            # If user entered a number, map to the choice
            try:
                idx = int(answer)
                if 1 <= idx <= len(choices):
                    return choices[idx - 1]
            except ValueError:
                pass
            return answer
        else:
            self.console.print(f"[bold yellow]{question}[/]")
            self.console.print(
                "[dim](Enter your response. For multi-line input, "
                "type each line then press Enter on an empty line to finish)[/]"
            )
            lines: list[str] = []
            while True:
                try:
                    line = input("> " if not lines else "  ")
                except EOFError:
                    break
                if line == "" and lines:
                    break
                lines.append(line)
            return "\n".join(lines)

    def _interactive_confirm(self, message: str) -> bool:
        """Prompt user for confirmation."""
        from rich.prompt import Confirm

        return Confirm.ask(f"[yellow]{message}[/]")
