"""Tier 1: DeviceModule — protocol-agnostic abstract base class."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DeviceInfo:
    identifier: str
    name: str
    manufacturer: str
    category: str
    model_patterns: list[str]
    connection_type: str


@dataclass
class DeviceHints:
    common_errors: dict[str, str] = field(default_factory=dict)
    setup_steps: list[str] = field(default_factory=list)
    os_specific: dict[str, dict] = field(default_factory=dict)
    documentation_urls: list[str] = field(default_factory=list)
    known_quirks: list[str] = field(default_factory=list)
    required_packages: list[str] = field(default_factory=list)


@dataclass
class DeviceDataSchema:
    fields: dict[str, str] = field(default_factory=dict)


class DeviceModule(ABC):
    @abstractmethod
    def get_info(self) -> DeviceInfo: ...

    @abstractmethod
    def get_hints(self, os: str) -> DeviceHints: ...

    @abstractmethod
    def detect(self, usb_devices: list[str], visa_resources: list[str]) -> bool: ...

    @abstractmethod
    def verify_connection(self) -> tuple[bool, str]: ...

    @abstractmethod
    def generate_example_code(self) -> str: ...

    @abstractmethod
    def get_data_schema(self) -> DeviceDataSchema: ...

    def _run_python(self, code: str, timeout: int = 10) -> tuple[bool, str]:
        """Write code to temp file, run with current Python, return (success, output)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            f.flush()
            try:
                result = subprocess.run(
                    [sys.executable, f.name],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                output = result.stdout
                if result.stderr:
                    output += ("\n" if output else "") + result.stderr
                return result.returncode == 0, output.strip()
            except subprocess.TimeoutExpired:
                return False, f"Timeout after {timeout} seconds"
            except Exception as e:
                return False, str(e)
