"""Data layer models — structures for community patterns and contributions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NormalizedStep:
    action: str  # "pip_install", "system_install", "permission_fix", "verify"
    detail: dict[str, Any] = field(default_factory=dict)
    # e.g. {"packages": ["pyvisa"]}, {"target": "libusb"}, {"pattern": "udev_rule"}


@dataclass
class ResolutionPattern:
    device_type: str
    os: str
    os_version: Optional[str]
    initial_state_fingerprint: Optional[str]
    steps: list[NormalizedStep]
    outcome: str  # "success" or "failed"


@dataclass
class ErrorResolution:
    device_type: Optional[str]
    os: Optional[str]
    error_fingerprint: str
    error_category: str
    explanation: str
    resolution_action: str
    resolution_detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorSequence:
    device_type: Optional[str]
    os: Optional[str]
    error_fingerprint: str
    next_error_fingerprint: str


@dataclass
class WorkingConfiguration:
    device_type: str
    os: str
    os_version: Optional[str]
    packages: dict[str, str]
    system_deps: list[str] = field(default_factory=list)
    permission_patterns: list[str] = field(default_factory=list)
    connection_method: str = "usb"


@dataclass
class SessionAnalysis:
    pattern: Optional[ResolutionPattern] = None
    error_resolutions: list[ErrorResolution] = field(default_factory=list)
    error_sequences: list[ErrorSequence] = field(default_factory=list)
    working_config: Optional[WorkingConfiguration] = None
