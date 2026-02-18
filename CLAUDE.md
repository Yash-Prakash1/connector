# Hardware Agent — Development Guide

## Project Overview

CLI tool (`hardware-agent`) that helps engineers connect to lab instruments using an AI agent. Runs locally, diagnoses connection issues iteratively via LLM, outputs working Python code. Cross-user learning system shares anonymized patterns via Supabase.

## Quick Commands

```bash
pip install -e ".[dev]"          # Install in development mode
pytest tests/ -v                 # Run all tests (302 tests)
pytest tests/ -q                 # Quick test summary
hardware-agent version           # Print version
hardware-agent detect            # Show environment info
hardware-agent list-devices      # List supported devices
hardware-agent connect -d rigol_ds1054z --yes  # Connect (needs API key + device)
hardware-agent config get        # View config
```

## Architecture

### Three-Tier Device System

```
Tier 1: DeviceModule ABC         (hardware_agent/devices/base.py)
Tier 2: VisaDevice/GenericDevice (hardware_agent/devices/visa_device.py, generic_device.py)
Tier 3: RigolDS1054ZModule       (hardware_agent/devices/rigol_ds1054z/module.py)
```

- Tier 1 is protocol-agnostic — no mention of VISA, SCPI, USB IDs
- Tier 2 has all shared VISA logic — detection, verification, hint merging
- Tier 3 is just class attributes + overrides (~65 lines per device)

### Key Directories

```
hardware_agent/
  core/         — orchestrator, LLM client, tools, executor, loop detector, environment
  devices/      — base classes, registry, device modules (subdirectories)
  data/         — SQLite store, Supabase community client, analysis, replay engine
  prompts/      — LLM system prompt and stuck prompt templates
tests/
  test_devices/ — device tier tests
  test_data/    — data layer tests
```

### Device Registry

Auto-discovers modules from `hardware_agent/devices/*/module.py` subdirectories. To add a new device:
1. Create `hardware_agent/devices/<device_name>/module.py`
2. Subclass `VisaDevice` (or `GenericDevice`)
3. Set class attributes (VENDOR_ID, PRODUCT_ID, etc.)
4. Override hooks as needed

### Data Flow

```
Session Start → Pull community patterns from Supabase → Cache in SQLite
             → Try replay if high-confidence pattern exists
             → Fall back to LLM agent loop if replay fails/unavailable
Session End   → Analyze iterations → Normalize to abstract steps → Push to Supabase
```

## Important Conventions

- **VISA resource strings** use raw hex (e.g., `USB0::1AB1::04CE::...`), NOT `0x` prefix format
- **SQLite database** lives at `~/.hardware-agent/data.db`
- **Supabase anon key** is safe to embed (RLS protects data)
- **Model resolution**: CLI `--model` flag → `HARDWARE_AGENT_MODEL` env → config DB → default `claude-sonnet-4-20250514`
- **Telemetry**: defaults to on, disable with `hardware-agent config set telemetry off`

## Testing

All tests use mocking — no real hardware, API calls, or Supabase needed.

- `conftest.py` has shared fixtures: `mock_environment`, `mock_rigol_module`, `temp_db`, `mock_agent_context`
- Test helpers: `mock_llm_response(tool_name, params)`, `make_iteration(...)`
- Registry tests call `_reset()` to clear cached state between tests

## Dependencies

Runtime: typer, rich, anthropic, supabase, pyvisa, pyvisa-py, pyusb
Dev: pytest, pytest-asyncio
