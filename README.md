# hardware-connector

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
pip install hardware-connector
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
hardware-connector connect

# Specify a device
hardware-connector connect --device rigol_ds1054z

# Auto-confirm all actions (no prompts)
hardware-connector connect --device rigol_ds1054z --yes
```

### Other commands

```bash
hardware-connector list-devices     # Show supported devices
hardware-connector detect           # Show environment info + detected devices
hardware-connector config get       # View configuration
hardware-connector config set model claude-sonnet-4-20250514  # Change LLM model
hardware-connector version          # Print version
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
hardware-connector config set telemetry off

# Change default model
hardware-connector config set model claude-sonnet-4-20250514
```

Model resolution order: `--model` flag → `HARDWARE_AGENT_MODEL` env var → config DB → default.

## License

Copyright (c) 2026 Yash Prakash. All rights reserved. See [LICENSE](LICENSE) for details.
