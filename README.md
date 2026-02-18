# hardware-agent

AI-powered CLI tool that helps engineers connect to lab instruments. It uses an LLM agent to diagnose connection issues, install dependencies, fix permissions, and generate working Python code — all from your terminal.

## How it works

1. Detects your OS, Python environment, USB devices, and VISA backends
2. Loads device-specific knowledge (pinouts, quirks, known errors)
3. Runs an AI agent loop that iteratively diagnoses and fixes connection issues
4. Outputs working Python code that communicates with your instrument

## Supported devices

| Device | Manufacturer | Type |
|--------|-------------|------|
| DS1054Z | Rigol | Oscilloscope |

More devices coming soon.

## Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
pip install git+https://github.com/Yash-Prakash1/connector.git
```

## Setup

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
```

## Usage

### Connect to a device

```bash
# Auto-detect connected device
hardware-agent connect

# Specify a device
hardware-agent connect --device rigol_ds1054z

# Auto-confirm all actions (no prompts)
hardware-agent connect --device rigol_ds1054z --yes
```

### Other commands

```bash
hardware-agent list-devices     # Show supported devices
hardware-agent detect           # Show environment info + detected devices
hardware-agent config get       # View configuration
hardware-agent config set model claude-sonnet-4-20250514  # Change LLM model
hardware-agent version          # Print version
```

### Options

| Flag | Description |
|------|-------------|
| `--device`, `-d` | Device identifier (e.g. `rigol_ds1054z`) |
| `--yes`, `-y` | Auto-confirm all actions |
| `--model`, `-m` | LLM model to use |
| `--max-iterations` | Max agent iterations (default: 20) |

## Configuration

```bash
# Disable telemetry
hardware-agent config set telemetry off

# Change default model
hardware-agent config set model claude-sonnet-4-20250514
```

Model resolution order: `--model` flag → `HARDWARE_AGENT_MODEL` env var → config DB → default.

## License

Copyright (c) 2026 Yash Prakash. All rights reserved. See [LICENSE](LICENSE) for details.
