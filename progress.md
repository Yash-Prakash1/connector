# Hardware Connector — Progress Tracker

## Phase 1: End-to-End Skeleton with DS1054Z — COMPLETE

**Status: Done** | All CLI commands working

### Source Files (26 Python files + 2 prompt files)

| File | Status | Description |
|------|--------|-------------|
| `hardware_agent/__init__.py` | Done | Version 0.1.0 |
| `hardware_agent/cli.py` | Done | 5 commands: connect, list-devices, detect, config, version |
| `hardware_agent/core/models.py` | Done | OS, Environment, ToolCall, ToolResult, Iteration, AgentContext, SessionResult |
| `hardware_agent/core/environment.py` | Done | EnvironmentDetector with OS/Python/USB/VISA/WSL detection |
| `hardware_agent/core/tools.py` | Done | 11 Anthropic tool_use schema definitions |
| `hardware_agent/core/executor.py` | Done | ToolExecutor with safety checks, confirmation flow |
| `hardware_agent/core/llm.py` | Done | LLMClient wrapping Anthropic API with prompt building |
| `hardware_agent/core/loop_detector.py` | Done | LoopDetector with action/error hashing |
| `hardware_agent/core/module_loader.py` | Done | Thin wrapper around device registry |
| `hardware_agent/core/orchestrator.py` | Done | Main agent loop (~385 lines) |
| `hardware_agent/devices/base.py` | Done | DeviceModule ABC, DeviceInfo, DeviceHints, DeviceDataSchema |
| `hardware_agent/devices/visa_device.py` | Done | VisaDevice tier 2 with hint merging |
| `hardware_agent/devices/generic_device.py` | Done | GenericDevice tier 2 fallback |
| `hardware_agent/devices/rigol_common.py` | Done | RIGOL_VENDOR_ID + get_rigol_common_hints() |
| `hardware_agent/devices/registry.py` | Done | Auto-discovery from subdirectories |
| `hardware_agent/devices/rigol_ds1054z/module.py` | Done | Tier 3 Rigol DS1054Z (~65 lines) |
| `hardware_agent/data/models.py` | Done | NormalizedStep, ResolutionPattern, ErrorResolution, etc. |
| `hardware_agent/data/store.py` | Done | SQLite DataStore with 6 tables |
| `hardware_agent/data/community.py` | Done | CommunityKnowledge Supabase client |
| `hardware_agent/data/analysis.py` | Done | Post-session analysis + step normalization |
| `hardware_agent/data/fingerprint.py` | Done | Initial state fingerprinting |
| `hardware_agent/data/replay.py` | Done | ReplayEngine for proven patterns |
| `hardware_agent/prompts/system.txt` | Done | LLM system prompt with template slots |
| `hardware_agent/prompts/stuck.txt` | Done | Loop breaker prompt |
| `pyproject.toml` | Done | Package config with entry point + deps |

---

## Phase 1.5: Troubleshoot Command — COMPLETE

**Status: Done** | 387 tests passing | `hardware-connector troubleshoot` working

Promise: **Diagnoses why a lab instrument setup is not behaving as expected and tells you what to check next.**

### New/Modified Source Files

| File | Status | Description |
|------|--------|-------------|
| `hardware_agent/cli.py` | Updated | Added `troubleshoot` command (6 commands total) |
| `hardware_agent/core/models.py` | Updated | Added `mode` field to `AgentContext` |
| `hardware_agent/core/tools.py` | Updated | Added 3 tool definitions + `TROUBLESHOOT_TOOLS` list (14 tools total) |
| `hardware_agent/core/executor.py` | Updated | Added `web_search`, `web_fetch`, `run_user_script` handlers + HTML-to-text extractor |
| `hardware_agent/core/llm.py` | Updated | Mode-aware prompt loading and initial message |
| `hardware_agent/core/orchestrator.py` | Updated | Mode support, skip replay in troubleshoot, new tool display |
| `hardware_agent/core/environment.py` | Updated | Added WSL2 detection |
| `hardware_agent/data/analysis.py` | Updated | Excluded new tools from replay normalization |
| `hardware_agent/devices/null_device.py` | **New** | NullDeviceModule for troubleshoot without device |
| `hardware_agent/devices/rigol_common.py` | Updated | Added MTP/USBTMC mode switch quirk |
| `hardware_agent/prompts/troubleshoot.txt` | **New** | Troubleshoot prompt: observe → diagnose → search → suggest → fix → verify |
| `hardware_agent/prompts/system.txt` | Updated | Improved rules: ask user's goal, validate before completing, WSL2/MTP patterns |
| `pyproject.toml` | Updated | Added `duckduckgo-search` dependency |

### Troubleshoot Agent Flow

1. **Listen** — ask the user what's going wrong
2. **Observe** — if connected, query the device to understand its actual state (settings, data, error registers)
3. **Diagnose** — analyze device data to form a specific diagnosis (not just parroting the user's words)
4. **Search** — web search + community DB with the real diagnosis
5. **Suggest** — present options to the user, ask before applying
6. **Fix** — apply the chosen fix via SCPI / code / config change
7. **Verify** — re-query device to confirm the fix worked

### Test Files (14 test files, 387 tests)

| File | Tests | Status |
|------|-------|--------|
| `tests/test_devices/test_base_module.py` | 16 | Pass |
| `tests/test_devices/test_visa_device.py` | 27 | Pass |
| `tests/test_devices/test_rigol_ds1054z.py` | 25 | Pass |
| `tests/test_devices/test_registry.py` | 15 | Pass |
| `tests/test_environment.py` | 71 | Pass |
| `tests/test_executor.py` | 58 | Pass |
| `tests/test_llm.py` | 18 | Pass |
| `tests/test_orchestrator.py` | 9 | Pass |
| `tests/test_loop_detector.py` | 14 | Pass |
| `tests/test_data/test_store.py` | 30 | Pass |
| `tests/test_data/test_community.py` | 17 | Pass |
| `tests/test_data/test_analysis.py` | 35 | Pass |
| `tests/test_data/test_fingerprint.py` | 9 | Pass |
| `tests/test_data/test_replay.py` | 16 | Pass |

### Currently Failing: **None** (387/387 pass)

---

## Known Gaps / Not Yet Implemented

### Minor gaps

| Item | Priority | Notes |
|------|----------|-------|
| `store.save_analysis()` is a no-op | Medium | Method exists but doesn't persist analysis results to SQLite |
| Supabase credentials are placeholders | Medium | URL and anon key need real values; env var overrides work |
| `hints.yaml` not created | Low | Hints are in Python code directly — works fine, YAML was optional |
| No `.gitignore` | Low | Should add to exclude __pycache__, .db files, etc. |
| No `README.md` | Low | Plan puts this in Phase 4 |

### Phase 2: Remaining Rigol Devices — NOT STARTED

| Device | Module Path | USB Product ID |
|--------|-------------|----------------|
| Rigol DP832 (power supply) | `hardware_agent/devices/rigol_dp832/module.py` | TBD from lsusb |
| Rigol DL3021 (electronic load) | `hardware_agent/devices/rigol_dl3021/module.py` | TBD from lsusb |
| Rigol M300 (DAQ/switching) | `hardware_agent/devices/rigol_m300/module.py` | TBD from lsusb |

Each is ~60-80 lines + test file. Architecture supports this — just set class attributes and override hooks.

### Phase 3: Non-Rigol Devices — NOT STARTED

| Device | Module Path | Notes |
|--------|-------------|-------|
| Siglent SDS1104X-E | `hardware_agent/devices/siglent_sds1104xe/module.py` | New vendor, tests cross-manufacturer support |
| Keithley 2400 | `hardware_agent/devices/keithley_2400/module.py` | May need GPIB resource string handling in VisaDevice |

### Phase 4: Polish — NOT STARTED

- Real hardware validation against all 4 physical Rigol devices
- Fix product IDs, hints, quirks discovered during testing
- `--verbose` / `--debug` flags
- Cost/token tracking display
- API key validation improvements
- Network error handling edge cases
- `README.md`

---

## Lines of Code

| Category | Files | Lines |
|----------|-------|-------|
| Source (hardware_agent/) | 29 | ~4,700 |
| Tests (tests/) | 14 | ~6,000 |
| **Total** | **43** | **~10,700** |
