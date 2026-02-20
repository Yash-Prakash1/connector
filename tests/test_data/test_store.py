"""Tests for hardware_agent.data.store — DataStore SQLite operations."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from hardware_agent.core.models import (
    Iteration,
    SessionResult,
    ToolCall,
    ToolResult,
)
from hardware_agent.data.models import (
    ErrorResolution,
    NormalizedStep,
    ResolutionPattern,
    SessionAnalysis,
)
from hardware_agent.data.store import DataStore


# ── Config ────────────────────────────────────────────────────────────


class TestConfig:
    """get_config / set_config and schema defaults."""

    def test_default_telemetry_is_true(self, temp_db: DataStore):
        assert temp_db.get_config("telemetry") == "true"

    def test_default_model(self, temp_db: DataStore):
        assert temp_db.get_config("model") == "claude-sonnet-4-20250514"

    def test_get_config_missing_key_returns_none(self, temp_db: DataStore):
        assert temp_db.get_config("nonexistent_key") is None

    def test_set_config_creates_new_key(self, temp_db: DataStore):
        temp_db.set_config("custom_key", "custom_value")
        assert temp_db.get_config("custom_key") == "custom_value"

    def test_set_config_overwrites_existing(self, temp_db: DataStore):
        temp_db.set_config("telemetry", "false")
        assert temp_db.get_config("telemetry") == "false"

    def test_set_config_then_get_returns_latest(self, temp_db: DataStore):
        temp_db.set_config("model", "gpt-4")
        temp_db.set_config("model", "claude-opus-4-20250514")
        assert temp_db.get_config("model") == "claude-opus-4-20250514"


# ── Sessions ──────────────────────────────────────────────────────────


class TestSessions:
    """create_session, complete_session, mark_session_shared."""

    def _create_test_session(self, store: DataStore, session_id: str = "sess-1"):
        store.create_session(
            session_id=session_id,
            device_type="rigol_ds1054z",
            device_name="Rigol DS1054Z",
            os_name="linux",
            os_version="Ubuntu 24.04",
            python_version="3.12.0",
            env_type="venv",
            fingerprint="abc123",
        )

    def test_create_session_inserts_row(self, temp_db: DataStore):
        self._create_test_session(temp_db)
        conn = temp_db._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row is not None
        assert row["device_type"] == "rigol_ds1054z"
        assert row["device_name"] == "Rigol DS1054Z"
        assert row["os"] == "linux"
        assert row["os_version"] == "Ubuntu 24.04"
        assert row["python_version"] == "3.12.0"
        assert row["env_type"] == "venv"
        assert row["initial_state_fingerprint"] == "abc123"
        assert row["outcome"] is None  # not yet completed

    def test_complete_session_updates_outcome(self, temp_db: DataStore):
        self._create_test_session(temp_db)
        result = SessionResult(
            success=True,
            session_id="sess-1",
            iterations=5,
            duration_seconds=42.5,
            summary="Connected to Rigol DS1054Z via USB-TMC",
            error_message=None,
        )
        temp_db.complete_session("sess-1", result)

        conn = temp_db._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row["outcome"] == "success"
        assert row["iteration_count"] == 5
        assert row["duration_seconds"] == pytest.approx(42.5)
        assert row["final_code"] == "Connected to Rigol DS1054Z via USB-TMC"
        assert row["updated_at"] is not None

    def test_complete_session_failed_outcome(self, temp_db: DataStore):
        self._create_test_session(temp_db)
        result = SessionResult(
            success=False,
            session_id="sess-1",
            iterations=3,
            duration_seconds=10.0,
            error_message="No device found",
        )
        temp_db.complete_session("sess-1", result)

        conn = temp_db._get_conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row["outcome"] == "failed"
        assert row["error_message"] == "No device found"

    def test_mark_session_shared(self, temp_db: DataStore):
        self._create_test_session(temp_db)
        conn = temp_db._get_conn()

        row = conn.execute(
            "SELECT pattern_uploaded FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row["pattern_uploaded"] == 0

        temp_db.mark_session_shared("sess-1")

        row = conn.execute(
            "SELECT pattern_uploaded FROM sessions WHERE id = ?", ("sess-1",)
        ).fetchone()
        assert row["pattern_uploaded"] == 1


# ── Iterations ────────────────────────────────────────────────────────


class TestIterations:
    """log_iteration."""

    def test_log_iteration_inserts_row(self, temp_db: DataStore):
        # Need a session first
        temp_db.create_session(
            session_id="sess-iter",
            device_type="rigol_ds1054z",
            device_name="Rigol DS1054Z",
            os_name="linux",
            os_version="Ubuntu 24.04",
            python_version="3.12.0",
            env_type="venv",
            fingerprint="fp1",
        )

        iteration = Iteration(
            number=1,
            timestamp=datetime(2025, 1, 15, 10, 30, 0),
            tool_call=ToolCall(
                id="tool_1",
                name="pip_install",
                parameters={"packages": ["pyvisa"]},
            ),
            result=ToolResult(
                success=True,
                stdout="Successfully installed pyvisa",
                stderr="",
                exit_code=0,
            ),
            duration_ms=350,
        )
        temp_db.log_iteration("sess-iter", iteration)

        conn = temp_db._get_conn()
        row = conn.execute(
            "SELECT * FROM iterations WHERE session_id = ?", ("sess-iter",)
        ).fetchone()
        assert row is not None
        assert row["iteration_number"] == 1
        assert row["tool_name"] == "pip_install"
        assert json.loads(row["tool_params"]) == {"packages": ["pyvisa"]}
        assert row["success"] == 1
        assert row["stdout"] == "Successfully installed pyvisa"
        assert row["duration_ms"] == 350

    def test_log_iteration_failed(self, temp_db: DataStore):
        temp_db.create_session(
            session_id="sess-fail",
            device_type="rigol_ds1054z",
            device_name="Rigol DS1054Z",
            os_name="linux",
            os_version="Ubuntu 24.04",
            python_version="3.12.0",
            env_type="venv",
            fingerprint="fp2",
        )
        iteration = Iteration(
            number=2,
            timestamp=datetime(2025, 1, 15, 10, 31, 0),
            tool_call=ToolCall(
                id="tool_2",
                name="check_device",
                parameters={},
            ),
            result=ToolResult(
                success=False,
                stderr="No backend available",
                exit_code=1,
            ),
            duration_ms=50,
        )
        temp_db.log_iteration("sess-fail", iteration)

        conn = temp_db._get_conn()
        row = conn.execute(
            "SELECT * FROM iterations WHERE session_id = ?", ("sess-fail",)
        ).fetchone()
        assert row["success"] == 0
        assert row["stderr"] == "No backend available"


# ── Community Patterns ────────────────────────────────────────────────


class TestCommunityPatterns:
    """cache_patterns / get_cached_patterns."""

    def test_cache_and_retrieve_patterns(self, temp_db: DataStore):
        patterns = [
            {
                "id": "pat-1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "initial_state_fingerprint": "fp_abc",
                "steps": [
                    {"action": "pip_install", "packages": ["pyvisa"]},
                    {"action": "verify", "pattern": "device_check"},
                ],
                "success_count": 10,
                "success_rate": 0.95,
                "confidence_score": 8.5,
            },
        ]
        temp_db.cache_patterns(patterns)
        cached = temp_db.get_cached_patterns("rigol_ds1054z", "linux")

        assert len(cached) == 1
        assert cached[0]["id"] == "pat-1"
        assert cached[0]["device_type"] == "rigol_ds1054z"
        assert cached[0]["os"] == "linux"
        assert isinstance(cached[0]["steps"], list)
        assert cached[0]["steps"][0]["action"] == "pip_install"
        assert cached[0]["confidence_score"] == 8.5

    def test_get_cached_patterns_returns_empty_for_unmatched(
        self, temp_db: DataStore
    ):
        patterns = [
            {
                "id": "pat-2",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [{"action": "pip_install", "packages": ["pyvisa"]}],
                "success_count": 5,
                "success_rate": 0.9,
                "confidence_score": 4.0,
            },
        ]
        temp_db.cache_patterns(patterns)
        cached = temp_db.get_cached_patterns("rigol_ds1054z", "macos")
        assert cached == []

    def test_cache_patterns_ordered_by_confidence(self, temp_db: DataStore):
        patterns = [
            {
                "id": "low",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [],
                "confidence_score": 2.0,
            },
            {
                "id": "high",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [],
                "confidence_score": 9.0,
            },
        ]
        temp_db.cache_patterns(patterns)
        cached = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(cached) == 2
        assert cached[0]["id"] == "high"
        assert cached[1]["id"] == "low"

    def test_cache_patterns_upserts_on_same_id(self, temp_db: DataStore):
        patterns_v1 = [
            {
                "id": "pat-dup",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [{"action": "pip_install", "packages": ["pyvisa"]}],
                "confidence_score": 3.0,
            },
        ]
        temp_db.cache_patterns(patterns_v1)

        patterns_v2 = [
            {
                "id": "pat-dup",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [{"action": "pip_install", "packages": ["pyvisa", "pyusb"]}],
                "confidence_score": 7.0,
            },
        ]
        temp_db.cache_patterns(patterns_v2)

        cached = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(cached) == 1
        assert cached[0]["confidence_score"] == 7.0
        assert "pyusb" in cached[0]["steps"][0]["packages"]


# ── Community Errors ──────────────────────────────────────────────────


class TestCommunityErrors:
    """cache_errors / get_cached_errors."""

    def test_cache_and_retrieve_errors(self, temp_db: DataStore):
        errors = [
            {
                "id": "err-1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "error_fingerprint": "fp_err_abc",
                "error_category": "permissions",
                "explanation": "USB permissions not set",
                "resolution_action": "bash",
                "resolution_detail": {"command": "sudo chmod ..."},
                "success_count": 20,
                "success_rate": 0.85,
            },
        ]
        temp_db.cache_errors(errors)
        cached = temp_db.get_cached_errors("rigol_ds1054z", "linux")

        assert len(cached) == 1
        assert cached[0]["error_fingerprint"] == "fp_err_abc"
        assert cached[0]["error_category"] == "permissions"
        assert isinstance(cached[0]["resolution_detail"], dict)
        assert cached[0]["resolution_detail"]["command"] == "sudo chmod ..."

    def test_get_cached_errors_includes_null_device_type(
        self, temp_db: DataStore
    ):
        errors = [
            {
                "id": "err-generic",
                "device_type": None,
                "os": None,
                "error_fingerprint": "fp_generic",
                "error_category": "backend",
                "explanation": "No backend available",
                "resolution_action": "pip_install",
                "resolution_detail": {"packages": ["pyvisa-py"]},
                "success_count": 50,
                "success_rate": 0.99,
            },
        ]
        temp_db.cache_errors(errors)
        cached = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        assert len(cached) == 1
        assert cached[0]["id"] == "err-generic"

    def test_get_cached_errors_ordered_by_success_rate(
        self, temp_db: DataStore
    ):
        errors = [
            {
                "id": "low-rate",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "error_fingerprint": "fp1",
                "success_rate": 0.3,
            },
            {
                "id": "high-rate",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "error_fingerprint": "fp2",
                "success_rate": 0.95,
            },
        ]
        temp_db.cache_errors(errors)
        cached = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        assert cached[0]["id"] == "high-rate"
        assert cached[1]["id"] == "low-rate"


# ── Upload Queue ──────────────────────────────────────────────────────


class TestUploadQueue:
    """queue_upload, get_pending_uploads, remove_upload, increment_upload_attempts."""

    def test_queue_upload_and_get_pending(self, temp_db: DataStore):
        payload = {"type": "pattern", "device_type": "rigol_ds1054z"}
        temp_db.queue_upload(payload)

        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["payload"] == payload
        assert pending[0]["attempts"] == 0

    def test_get_pending_uploads_empty(self, temp_db: DataStore):
        assert temp_db.get_pending_uploads() == []

    def test_queue_multiple_uploads_ordered_by_creation(
        self, temp_db: DataStore
    ):
        temp_db.queue_upload({"order": 1})
        temp_db.queue_upload({"order": 2})
        temp_db.queue_upload({"order": 3})

        pending = temp_db.get_pending_uploads()
        assert len(pending) == 3
        assert pending[0]["payload"]["order"] == 1
        assert pending[2]["payload"]["order"] == 3

    def test_remove_upload(self, temp_db: DataStore):
        temp_db.queue_upload({"data": "to_remove"})
        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1

        upload_id = pending[0]["id"]
        temp_db.remove_upload(upload_id)

        assert temp_db.get_pending_uploads() == []

    def test_increment_upload_attempts(self, temp_db: DataStore):
        temp_db.queue_upload({"data": "retry_me"})
        pending = temp_db.get_pending_uploads()
        upload_id = pending[0]["id"]
        assert pending[0]["attempts"] == 0

        temp_db.increment_upload_attempts(upload_id)
        pending = temp_db.get_pending_uploads()
        assert pending[0]["attempts"] == 1

        temp_db.increment_upload_attempts(upload_id)
        pending = temp_db.get_pending_uploads()
        assert pending[0]["attempts"] == 2

    def test_remove_one_upload_leaves_others(self, temp_db: DataStore):
        temp_db.queue_upload({"data": "keep"})
        temp_db.queue_upload({"data": "remove"})
        pending = temp_db.get_pending_uploads()

        remove_id = pending[1]["id"]
        temp_db.remove_upload(remove_id)

        remaining = temp_db.get_pending_uploads()
        assert len(remaining) == 1
        assert remaining[0]["payload"]["data"] == "keep"


# ── Save Analysis ────────────────────────────────────────────────────


def _make_analysis(
    outcome: str = "success",
    device_type: str = "rigol_ds1054z",
    os_name: str = "linux",
    fingerprint: str = "fp_abc",
    steps: list[NormalizedStep] | None = None,
    error_resolutions: list[ErrorResolution] | None = None,
) -> SessionAnalysis:
    """Helper to build a SessionAnalysis for testing."""
    if steps is None:
        steps = [
            NormalizedStep(action="pip_install", detail={"packages": ["pyvisa"]}),
            NormalizedStep(action="verify", detail={"pattern": "device_check"}),
        ]
    return SessionAnalysis(
        pattern=ResolutionPattern(
            device_type=device_type,
            os=os_name,
            os_version=None,
            initial_state_fingerprint=fingerprint,
            steps=steps,
            outcome=outcome,
        ),
        error_resolutions=error_resolutions or [],
    )


class TestSaveAnalysis:
    """save_analysis — persist patterns and error resolutions."""

    def test_successful_session_inserts_pattern(self, temp_db: DataStore):
        analysis = _make_analysis(outcome="success")
        temp_db.save_analysis("sess-1", analysis)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(patterns) == 1
        assert patterns[0]["device_type"] == "rigol_ds1054z"
        assert patterns[0]["os"] == "linux"
        assert patterns[0]["success_count"] == 1
        assert patterns[0]["success_rate"] == 1.0
        assert isinstance(patterns[0]["steps"], list)
        assert patterns[0]["steps"][0]["action"] == "pip_install"

    def test_failed_session_inserts_pattern_with_zero_success(
        self, temp_db: DataStore
    ):
        analysis = _make_analysis(outcome="failed")
        temp_db.save_analysis("sess-1", analysis)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(patterns) == 1
        assert patterns[0]["success_count"] == 0
        assert patterns[0]["success_rate"] == 0.0

    def test_duplicate_success_increments_count(self, temp_db: DataStore):
        analysis = _make_analysis(outcome="success")
        temp_db.save_analysis("sess-1", analysis)
        temp_db.save_analysis("sess-2", analysis)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(patterns) == 1
        assert patterns[0]["success_count"] == 2
        assert patterns[0]["success_rate"] == 1.0

    def test_success_then_failure_decreases_rate(self, temp_db: DataStore):
        success = _make_analysis(outcome="success")
        failure = _make_analysis(outcome="failed")
        temp_db.save_analysis("sess-1", success)
        temp_db.save_analysis("sess-2", failure)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(patterns) == 1
        assert patterns[0]["success_count"] == 1
        assert patterns[0]["success_rate"] == pytest.approx(0.5)

    def test_multiple_successes_build_confidence(self, temp_db: DataStore):
        analysis = _make_analysis(outcome="success")
        for i in range(5):
            temp_db.save_analysis(f"sess-{i}", analysis)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert patterns[0]["success_count"] == 5
        assert patterns[0]["success_rate"] == 1.0

    def test_error_resolution_inserted(self, temp_db: DataStore):
        analysis = _make_analysis(
            error_resolutions=[
                ErrorResolution(
                    device_type="rigol_ds1054z",
                    os="linux",
                    error_fingerprint="abc123",
                    error_category="backend",
                    explanation="No backend available",
                    resolution_action="pip_install",
                    resolution_detail={"packages": ["pyvisa-py"]},
                ),
            ],
        )
        temp_db.save_analysis("sess-1", analysis)

        errors = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        assert len(errors) >= 1
        match = [e for e in errors if e["error_fingerprint"] == "abc123"]
        assert len(match) == 1
        assert match[0]["error_category"] == "backend"
        assert match[0]["resolution_action"] == "pip_install"
        assert match[0]["success_count"] == 1

    def test_error_resolution_increments_on_duplicate(self, temp_db: DataStore):
        er = ErrorResolution(
            device_type="rigol_ds1054z",
            os="linux",
            error_fingerprint="abc123",
            error_category="backend",
            explanation="No backend available",
            resolution_action="pip_install",
            resolution_detail={"packages": ["pyvisa-py"]},
        )
        analysis = _make_analysis(error_resolutions=[er])
        temp_db.save_analysis("sess-1", analysis)
        temp_db.save_analysis("sess-2", analysis)

        errors = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        match = [e for e in errors if e["error_fingerprint"] == "abc123"]
        assert match[0]["success_count"] == 2

    def test_non_session_analysis_is_ignored(self, temp_db: DataStore):
        """Passing a non-SessionAnalysis object is a no-op."""
        temp_db.save_analysis("sess-1", {"not": "a SessionAnalysis"})
        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert patterns == []

    def test_analysis_without_pattern_saves_only_errors(
        self, temp_db: DataStore
    ):
        analysis = SessionAnalysis(
            pattern=None,
            error_resolutions=[
                ErrorResolution(
                    device_type="rigol_ds1054z",
                    os="linux",
                    error_fingerprint="xyz789",
                    error_category="permissions",
                    explanation="Permission denied",
                    resolution_action="bash",
                    resolution_detail={"command": "sudo chmod 666 /dev/usbtmc0"},
                ),
            ],
        )
        temp_db.save_analysis("sess-1", analysis)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert patterns == []
        errors = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        assert len(errors) == 1

    def test_end_to_end_save_then_replay_finds_pattern(
        self, temp_db: DataStore
    ):
        """After enough successful saves, the replay engine finds the pattern."""
        from hardware_agent.data.replay import ReplayEngine

        analysis = _make_analysis(outcome="success")
        # Save 5 successful sessions to meet CONFIDENCE_THRESHOLD
        for i in range(5):
            temp_db.save_analysis(f"sess-{i}", analysis)

        engine = ReplayEngine()
        candidate = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "fp_abc", temp_db
        )
        assert candidate is not None
        assert candidate["success_count"] == 5
        assert candidate["success_rate"] == 1.0

    def test_insufficient_successes_not_replayed(self, temp_db: DataStore):
        """Below threshold, replay engine returns None."""
        from hardware_agent.data.replay import ReplayEngine

        analysis = _make_analysis(outcome="success")
        for i in range(3):
            temp_db.save_analysis(f"sess-{i}", analysis)

        engine = ReplayEngine()
        candidate = engine.find_replay_candidate(
            "rigol_ds1054z", "linux", "fp_abc", temp_db
        )
        assert candidate is None

    def test_different_steps_create_separate_patterns(
        self, temp_db: DataStore
    ):
        analysis_a = _make_analysis(
            steps=[NormalizedStep(action="pip_install", detail={"packages": ["pyvisa"]})]
        )
        analysis_b = _make_analysis(
            steps=[NormalizedStep(action="system_install", detail={"target": "libusb"})]
        )
        temp_db.save_analysis("sess-1", analysis_a)
        temp_db.save_analysis("sess-2", analysis_b)

        patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(patterns) == 2
