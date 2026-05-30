# hardware-connector

AI powered CLI tool that helps engineers connect to lab instruments. It uses an LLM
agent to diagnose connection issues, install dependencies, fix permissions, and
generate working Python code, all from your terminal.

## The problem it solves

Talking to a benchtop instrument from code is often the hardest part of an experiment.
You fight with VISA backends, USB permissions, driver installs, and cryptic resource
strings before you ever read a single measurement. hardware-connector turns that into
a conversation. It inspects your machine, reasons about what is wrong, fixes it, and
hands you Python code that actually talks to your device.

## How it works

1. Detects your OS, Python environment, USB devices, and VISA backends.
2. Loads device specific knowledge such as pinouts, quirks, and known errors.
3. Runs an AI agent loop that iteratively diagnoses and fixes connection issues.
4. Outputs working Python code that communicates with your instrument.

## Architecture

The codebase is built to add new instruments and new LLM vendors without touching the
core agent.

* **Three tier device model.** A `DeviceModule` abstract base sits above
  `VisaDevice` and `GenericDevice`, which in turn sit above specific instruments such
  as the Rigol DS1054Z. Shared behavior lives high up, device quirks live low down.
* **Auto discovering device registry.** Devices are found at runtime by importing
  every `module.py` under `hardware_agent/devices/*`, so adding an instrument is a
  matter of dropping in a new folder.
* **Pluggable LLM providers.** A `BaseLLMProvider` abstract base backs concrete
  Anthropic, OpenAI, and Google Gemini providers, selected by configuration.
* **Agentic loop with safety rails.** An orchestrator drives the diagnose and fix
  loop, with a loop detector to stop the agent from repeating itself and an executor
  that runs shell actions under your confirmation.
* **Local and community knowledge.** Results are stored in a local SQLite database,
  with Supabase used for shared community knowledge.

## Supported devices

| Device | Manufacturer | Type |
|--------|-------------|------|
| DS1054Z | Rigol | Oscilloscope |

More devices are planned.

## Requirements

- Python 3.10+
- An API key for one of the supported LLM providers, for example an
  [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
pip install hardware-connector
```

## Setup

Set the API key for your chosen provider:

```bash
export ANTHROPIC_API_KEY='sk-ant-...'
# or OPENAI_API_KEY, or a Google Gemini key, depending on your configured provider
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

Model resolution order: `--model` flag, then `HARDWARE_AGENT_MODEL` env var, then the
config database, then the default.

## License

Copyright (c) 2026 Yash Prakash. All rights reserved. See [LICENSE](LICENSE) for details.
