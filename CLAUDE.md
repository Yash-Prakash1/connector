# Hardware Connector — Development Guide

## Project Overview

CLI tool (`hardware-connector`) that helps engineers connect to lab instruments and diagnose why setups aren't behaving as expected. Two modes:
- **`connect`** — AI agent iteratively diagnoses connection issues, outputs working Python code
- **`troubleshoot`** — Conversational agent that observes the device, searches the web, and tells you what to check next

Cross-user learning system shares anonymized patterns via Supabase.

## Quick Commands

```bash
pip install -e ".[dev]"          # Install in development mode
pytest tests/ -v                 # Run all tests
pytest tests/ -q                 # Quick test summary
hardware-connector version           # Print version
hardware-connector detect            # Show environment info
hardware-connector list-devices      # List supported devices
hardware-connector connect -d rigol_ds1054z --yes  # Connect (needs API key + device)
hardware-connector troubleshoot      # Troubleshoot (needs API key, device optional)
hardware-connector config get        # View config
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
  devices/      — base classes, registry, device modules (subdirectories), null_device
  data/         — SQLite store, Supabase community client, analysis, replay engine
  prompts/      — system.txt (connect), troubleshoot.txt (troubleshoot), stuck.txt (loop breaker)
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

**Connect mode:**
```
Session Start → Pull community patterns from Supabase → Cache in SQLite
             → Try replay if high-confidence pattern exists
             → Fall back to LLM agent loop if replay fails/unavailable
Session End   → Analyze iterations → Normalize to abstract steps → Push to Supabase
```

**Troubleshoot mode:**
```
Session Start → Pull community patterns → Skip replay (always interactive)
             → LLM agent loop with extended tools (web search, web fetch, run user script)
             → Agent observes device state → diagnoses → searches with real diagnosis
             → Presents options → user confirms → agent applies fix → verifies
```

## Important Conventions

- **VISA resource strings** use raw hex (e.g., `USB0::1AB1::04CE::...`), NOT `0x` prefix format
- **SQLite database** lives at `~/.hardware-agent/data.db`
- **Supabase anon key** is safe to embed (RLS protects data)
- **Model resolution**: CLI `--model` flag → `HARDWARE_AGENT_MODEL` env → config DB → default `claude-sonnet-4-20250514`
- **Telemetry**: defaults to on, disable with `hardware-connector config set telemetry off`

## Testing

All tests use mocking — no real hardware, API calls, or Supabase needed.

- `conftest.py` has shared fixtures: `mock_environment`, `mock_rigol_module`, `temp_db`, `mock_agent_context`
- Test helpers: `mock_llm_response(tool_name, params)`, `make_iteration(...)`
- Registry tests call `_reset()` to clear cached state between tests

### Orchestrator Modes

The `Orchestrator` accepts a `mode` parameter (`"connect"` or `"troubleshoot"`):
- **`connect`**: Uses `TOOLS` (11 tools), loads `system.txt` prompt, tries replay before LLM loop
- **`troubleshoot`**: Uses `TROUBLESHOOT_TOOLS` (14 tools = TOOLS + web_search, web_fetch, run_user_script), loads `troubleshoot.txt` prompt, skips replay, always interactive

`NullDeviceModule` (`devices/null_device.py`) is used when no device is detected in troubleshoot mode. Avoids making `device_module` nullable across the codebase.

`AgentContext.mode` field tells the LLM client which prompt template and initial message to use.

## Dependencies

Runtime: typer, rich, anthropic, supabase, pyvisa, pyvisa-py, pyusb, duckduckgo-search
Dev: pytest, pytest-asyncio
