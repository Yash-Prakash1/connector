"""Tool definitions for the LLM agent — Anthropic tool_use schema."""

from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "bash",
        "description": (
            "Run a shell command. Use for system-level operations like checking "
            "USB devices, installing system packages, managing udev rules, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the contents of a file. Optionally specify line range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "First line to read (1-indexed, optional)",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Last line to read (1-indexed, optional)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write content to a file. Creates parent directories if needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write",
                },
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Write mode (default: overwrite)",
                    "default": "overwrite",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "check_installed",
        "description": (
            "Check if a Python package is installed and get its version."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name to check",
                },
            },
            "required": ["package"],
        },
    },
    {
        "name": "pip_install",
        "description": (
            "Install Python packages using pip in the current environment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of package names to install",
                },
            },
            "required": ["packages"],
        },
    },
    {
        "name": "check_device",
        "description": (
            "Run device-specific verification. Attempts to connect and query "
            "the device identity (*IDN? for VISA devices)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_visa_resources",
        "description": (
            "List all VISA resources visible to pyvisa. Requires pyvisa to be installed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_usb_devices",
        "description": (
            "List all USB devices connected to the system."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python code in the current environment. "
            "Use for testing imports, running diagnostic scripts, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 10)",
                    "default": 10,
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "complete",
        "description": (
            "Signal that you have successfully connected to the device. "
            "Provide the working Python code that connects to and communicates "
            "with the device."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Complete, runnable Python code for device connection",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was done to establish the connection",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "give_up",
        "description": (
            "Signal that you cannot establish a connection. "
            "Provide a reason and suggestions for the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the connection could not be established",
                },
                "suggestions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Suggestions for the user to try manually",
                },
            },
            "required": ["reason"],
        },
    },
]
