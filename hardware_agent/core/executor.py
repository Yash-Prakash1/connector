"""Tool executor — executes tools called by the LLM with safety checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Optional

from hardware_agent.core.models import Environment, ToolCall, ToolResult
from hardware_agent.devices.base import DeviceModule

ConfirmCallback = Callable[[str], bool]
AskUserCallback = Callable[[str, Optional[list[str]]], str]


_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer"})


class _HTMLTextExtractor(HTMLParser):
    """Simple HTML-to-text extractor that skips script/style/nav tags."""

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._pieces).split())


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text, skipping script/style/nav tags."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    "dd if=",
    ":(){:|:&};:",
    "> /dev/sda",
    "chmod -R 777 /",
]

REQUIRES_CONFIRMATION = [
    "sudo ",
    "rm ",
    "pip uninstall",
    "apt remove",
    "brew uninstall",
]


class ToolExecutor:
    """Executes tools called by the LLM agent."""

    def __init__(
        self,
        environment: Environment,
        device_module: DeviceModule,
        confirm_callback: Optional[ConfirmCallback] = None,
        ask_user_callback: Optional[AskUserCallback] = None,
    ):
        self.environment = environment
        self.device_module = device_module
        self.confirm_callback = confirm_callback or (lambda _: True)
        self.ask_user_callback = ask_user_callback

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Dispatch tool call to the appropriate handler."""
        handler_name = f"_handle_{tool_call.name}"
        handler = getattr(self, handler_name, None)
        if handler is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_call.name}",
            )
        try:
            return handler(tool_call.parameters)
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Tool execution error: {e}",
            )

    def _handle_bash(self, params: dict[str, Any]) -> ToolResult:
        command = params.get("command", "")
        timeout = params.get("timeout", 30)

        for blocked in BLOCKED_COMMANDS:
            if blocked in command:
                return ToolResult(
                    success=False,
                    error=f"Blocked command: {blocked}",
                )

        needs_confirm = any(pat in command for pat in REQUIRES_CONFIRMATION)
        if needs_confirm and not self.confirm_callback(
            f"Run command: {command}"
        ):
            return ToolResult(
                success=False,
                error="Command declined by user",
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return ToolResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout} seconds",
            )

    def _handle_read_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        start_line = params.get("start_line")
        end_line = params.get("end_line")
        try:
            content = Path(path).read_text()
            if start_line or end_line:
                lines = content.splitlines()
                start = (start_line or 1) - 1
                end = end_line or len(lines)
                content = "\n".join(lines[start:end])
            return ToolResult(success=True, stdout=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _handle_write_file(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")
        mode = params.get("mode", "overwrite")

        if not self.confirm_callback(f"Write file: {path}"):
            return ToolResult(success=False, error="Write declined by user")

        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with open(p, "a") as f:
                    f.write(content)
            else:
                p.write_text(content)
            return ToolResult(success=True, stdout=f"Written to {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _handle_check_installed(self, params: dict[str, Any]) -> ToolResult:
        package = params.get("package", "").lower()
        version = self.environment.installed_packages.get(package)
        if version:
            return ToolResult(
                success=True,
                stdout=f"{package} is installed (version {version})",
            )
        return ToolResult(
            success=False,
            stdout=f"{package} is NOT installed",
        )

    def _handle_pip_install(self, params: dict[str, Any]) -> ToolResult:
        packages = params.get("packages", [])
        if not packages:
            return ToolResult(success=False, error="No packages specified")

        pkg_str = " ".join(packages)
        if not self.confirm_callback(f"Install packages: {pkg_str}"):
            return ToolResult(
                success=False, error="Installation declined by user"
            )

        pip_cmd = self.environment.pip_path.split() if " " in self.environment.pip_path else [self.environment.pip_path]
        try:
            result = subprocess.run(
                pip_cmd + ["install"] + packages,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                # Update installed packages cache
                for pkg in packages:
                    self.environment.installed_packages[pkg.lower()] = "installed"
            return ToolResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="pip install timed out after 120 seconds",
            )

    def _handle_check_device(self, params: dict[str, Any]) -> ToolResult:
        success, message = self.device_module.verify_connection()
        return ToolResult(
            success=success,
            stdout=message if success else "",
            error="" if success else message,
        )

    def _handle_list_visa_resources(self, params: dict[str, Any]) -> ToolResult:
        code = """\
import pyvisa
rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
if resources:
    for r in resources:
        print(r)
else:
    print("No VISA resources found")
"""
        return self._run_python_code(code)

    def _handle_list_usb_devices(self, params: dict[str, Any]) -> ToolResult:
        os_val = self.environment.os.value
        if os_val == "linux":
            return self._handle_bash({"command": "lsusb", "timeout": 5})
        elif os_val == "macos":
            return self._handle_bash(
                {"command": "system_profiler SPUSBDataType", "timeout": 10}
            )
        elif os_val == "windows":
            return self._handle_bash(
                {"command": "powershell -Command \"Get-PnpDevice -Class USB\"",
                 "timeout": 10}
            )
        return ToolResult(
            success=False, error=f"Unsupported OS: {os_val}"
        )

    def _handle_run_python(self, params: dict[str, Any]) -> ToolResult:
        code = params.get("code", "")
        timeout = params.get("timeout", 10)
        return self._run_python_code(code, timeout)

    def _handle_ask_user(self, params: dict[str, Any]) -> ToolResult:
        question = params.get("question", "").strip()
        choices = params.get("choices")

        if not question:
            return ToolResult(
                success=False,
                error="No question provided",
            )

        if self.ask_user_callback is None:
            return ToolResult(
                success=False,
                error="Cannot ask user in non-interactive mode. Try a different approach.",
            )

        try:
            answer = self.ask_user_callback(question, choices)
            return ToolResult(success=True, stdout=answer)
        except (KeyboardInterrupt, EOFError):
            return ToolResult(
                success=False,
                error="User cancelled the prompt",
            )

    def _handle_complete(self, params: dict[str, Any]) -> ToolResult:
        summary = params.get("summary", "Session completed.")
        return ToolResult(
            success=True,
            output=summary,
            stdout=summary,
            is_terminal=True,
        )

    def _handle_give_up(self, params: dict[str, Any]) -> ToolResult:
        reason = params.get("reason", "Unknown reason")
        suggestions = params.get("suggestions", [])
        output = f"Reason: {reason}"
        if suggestions:
            output += "\n\nSuggestions:\n"
            for s in suggestions:
                output += f"  - {s}\n"
        return ToolResult(
            success=False,
            output=output,
            error=reason,
            is_terminal=True,
        )

    def _handle_web_search(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "").strip()
        max_results = params.get("max_results", 5)
        if not query:
            return ToolResult(success=False, error="No search query provided")
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return ToolResult(
                success=False,
                error=(
                    "duckduckgo-search is not installed. "
                    "Install it with: pip install duckduckgo-search"
                ),
            )
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return ToolResult(success=True, stdout="No results found.")
            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                url = r.get("href", "")
                snippet = r.get("body", "")
                lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
            return ToolResult(success=True, stdout="\n\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")

    def _handle_web_fetch(self, params: dict[str, Any]) -> ToolResult:
        url = params.get("url", "").strip()
        if not url:
            return ToolResult(success=False, error="No URL provided")
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "hardware-connector/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            text = _html_to_text(raw)
            if len(text) > 8000:
                text = text[:8000] + "\n\n... (truncated)"
            return ToolResult(success=True, stdout=text)
        except Exception as e:
            return ToolResult(success=False, error=f"Fetch failed: {e}")

    def _handle_run_user_script(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        timeout = min(params.get("timeout", 30), 120)
        p = Path(path)
        if not p.is_file():
            return ToolResult(
                success=False,
                error=f"File not found: {path}",
            )
        # Always require user confirmation, regardless of auto_confirm
        if not self.confirm_callback(
            f"Run user script: {path} (timeout: {timeout}s)"
        ):
            return ToolResult(
                success=False,
                error="Script execution declined by user",
            )
        code = p.read_text()
        return self._run_python_code(code, timeout)

    def _run_python_code(self, code: str, timeout: int = 10) -> ToolResult:
        """Execute Python code in a temp file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            f.flush()
            try:
                result = subprocess.run(
                    [self.environment.python_path, f.name],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                return ToolResult(
                    success=result.returncode == 0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                )
            except subprocess.TimeoutExpired:
                return ToolResult(
                    success=False,
                    error=f"Python execution timed out after {timeout} seconds",
                )
