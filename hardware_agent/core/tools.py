"""Tool definitions for the LLM agent — Anthropic tool_use schema."""

from __future__ import annotations

_WEB_SEARCH_TOOL: dict = {
    "name": "web_search",
    "description": (
        "Search the web for solutions to errors, driver issues, or "
        "device-specific troubleshooting information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g. 'pyvisa no backend available linux')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}

_WEB_FETCH_TOOL: dict = {
    "name": "web_fetch",
    "description": (
        "Fetch and extract text content from a URL. Use to read documentation "
        "pages, forum posts, or other web resources found via web_search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL to fetch",
            },
        },
        "required": ["url"],
    },
}

_RUN_USER_SCRIPT_TOOL: dict = {
    "name": "run_user_script",
    "description": (
        "Run an existing Python script file from the user's filesystem. "
        "Always requires user confirmation before execution. Use to reproduce "
        "errors the user is experiencing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the Python script file",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 120)",
                "default": 30,
            },
        },
        "required": ["path"],
    },
}

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
        "name": "ask_user",
        "description": (
            "Ask the user a question. Use this when you need information you "
            "cannot determine programmatically — connection type, physical "
            "device state, operating environment, or confirmation that a "
            "physical action has been performed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                },
                "choices": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional multiple-choice options",
                },
            },
            "required": ["question"],
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
            "Signal that the session is finished. Call this only when "
            "the user says they are done working with the device."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief summary of what was accomplished",
                },
            },
            "required": ["summary"],
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

TROUBLESHOOT_TOOLS: list[dict] = TOOLS + [
    _WEB_SEARCH_TOOL,
    _WEB_FETCH_TOOL,
    _RUN_USER_SCRIPT_TOOL,
]
