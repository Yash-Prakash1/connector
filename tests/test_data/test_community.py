"""Tests for hardware_agent.data.community — CommunityKnowledge client."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from hardware_agent.data.community import CommunityKnowledge
from hardware_agent.data.store import DataStore


# ── Helpers ───────────────────────────────────────────────────────────


def _mock_supabase_client(
    patterns_data=None,
    errors_data=None,
    configs_data=None,
    insert_side_effect=None,
):
    """Build a MagicMock that mimics the supabase client query builder chain.

    Each .table(...).select(...).eq(...).order(...).limit(...).execute() chain
    returns a response object with a `data` attribute.
    """
    client = MagicMock()

    def _table(name):
        table_mock = MagicMock()

        # SELECT chain ── .select().eq().eq()/or_().order().limit().execute()
        select_chain = MagicMock()

        if name == "resolution_patterns":
            resp = MagicMock()
            resp.data = patterns_data or []
            select_chain.eq.return_value = select_chain
            select_chain.or_.return_value = select_chain
            select_chain.order.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value = resp

        elif name == "error_resolutions":
            resp = MagicMock()
            resp.data = errors_data or []
            select_chain.eq.return_value = select_chain
            select_chain.or_.return_value = select_chain
            select_chain.order.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value = resp

        elif name == "working_configurations":
            resp = MagicMock()
            resp.data = configs_data or []
            select_chain.eq.return_value = select_chain
            select_chain.or_.return_value = select_chain
            select_chain.order.return_value = select_chain
            select_chain.limit.return_value = select_chain
            select_chain.execute.return_value = resp

        elif name == "contributions":
            # INSERT chain ── .insert(payload).execute()
            insert_chain = MagicMock()
            if insert_side_effect:
                insert_chain.execute.side_effect = insert_side_effect
            else:
                insert_chain.execute.return_value = MagicMock()
            table_mock.insert.return_value = insert_chain
            return table_mock

        table_mock.select.return_value = select_chain
        return table_mock

    client.table.side_effect = _table
    return client


# ── is_configured ─────────────────────────────────────────────────────


class TestIsConfigured:
    """Credential resolution: env var → config DB → disabled."""

    def test_not_configured_by_default(self, temp_db: DataStore):
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_configured is False

    def test_configured_via_constructor(self, temp_db: DataStore):
        ck = CommunityKnowledge(
            store=temp_db,
            supabase_url="https://x.supabase.co",
            supabase_key="key-123",
        )
        assert ck.is_configured is True
        assert ck.supabase_url == "https://x.supabase.co"
        assert ck.supabase_key == "key-123"

    def test_configured_via_config_db(self, temp_db: DataStore):
        temp_db.set_config("supabase-url", "https://db.supabase.co")
        temp_db.set_config("supabase-key", "db-key")
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_configured is True
        assert ck.supabase_url == "https://db.supabase.co"
        assert ck.supabase_key == "db-key"

    @patch.dict(
        "os.environ",
        {
            "HARDWARE_AGENT_SUPABASE_URL": "https://env.supabase.co",
            "HARDWARE_AGENT_SUPABASE_KEY": "env-key",
        },
    )
    def test_configured_via_env_vars(self, temp_db: DataStore):
        # Env vars take priority over config DB
        temp_db.set_config("supabase-url", "https://db.supabase.co")
        temp_db.set_config("supabase-key", "db-key")
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_configured is True
        assert ck.supabase_url == "https://env.supabase.co"
        assert ck.supabase_key == "env-key"

    def test_partial_config_not_configured(self, temp_db: DataStore):
        temp_db.set_config("supabase-url", "https://db.supabase.co")
        # No key set
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_configured is False

    def test_get_client_returns_none_when_not_configured(
        self, temp_db: DataStore
    ):
        ck = CommunityKnowledge(store=temp_db)
        assert ck._get_client() is None

    def test_push_queues_when_not_configured(self, temp_db: DataStore):
        ck = CommunityKnowledge(store=temp_db)
        result = ck.push_contribution({"device_type": "test"})
        assert result is False
        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["payload"] == {"device_type": "test"}


# ── is_enabled ────────────────────────────────────────────────────────


class TestIsEnabled:
    """Telemetry toggle via config."""

    def test_enabled_by_default(self, temp_db: DataStore):
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_enabled() is True

    def test_disabled_when_config_off(self, temp_db: DataStore):
        temp_db.set_config("telemetry", "off")
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_enabled() is False

    def test_disabled_when_config_false(self, temp_db: DataStore):
        temp_db.set_config("telemetry", "false")
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_enabled() is False

    def test_enabled_for_arbitrary_truthy_value(self, temp_db: DataStore):
        temp_db.set_config("telemetry", "yes")
        ck = CommunityKnowledge(store=temp_db)
        assert ck.is_enabled() is True


# ── pull_patterns ─────────────────────────────────────────────────────


class TestPullPatterns:
    """Pulling community data from Supabase, with caching."""

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_pull_patterns_fetches_and_caches(
        self, mock_get_client, temp_db: DataStore
    ):
        patterns = [
            {
                "id": "p1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "initial_state_fingerprint": None,
                "steps": [{"action": "pip_install", "packages": ["pyvisa"]}],
                "success_count": 10,
                "success_rate": 0.95,
                "confidence_score": 8.0,
            },
        ]
        errors = [
            {
                "id": "e1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "error_fingerprint": "fp1",
                "error_category": "backend",
                "explanation": "No backend",
                "resolution_action": "pip_install",
                "resolution_detail": {},
                "success_count": 5,
                "success_rate": 0.9,
            },
        ]
        configs = [{"id": "c1", "device_type": "rigol_ds1054z", "os": "linux"}]

        mock_client = _mock_supabase_client(
            patterns_data=patterns,
            errors_data=errors,
            configs_data=configs,
        )
        mock_get_client.return_value = mock_client

        ck = CommunityKnowledge(store=temp_db)
        result = ck.pull_patterns("rigol_ds1054z", "linux")

        assert result is not None
        assert result["patterns"] == patterns
        assert result["errors"] == errors
        assert result["working_configs"] == configs

        # Verify data was cached locally
        cached_patterns = temp_db.get_cached_patterns("rigol_ds1054z", "linux")
        assert len(cached_patterns) == 1
        assert cached_patterns[0]["id"] == "p1"

        cached_errors = temp_db.get_cached_errors("rigol_ds1054z", "linux")
        assert len(cached_errors) == 1
        assert cached_errors[0]["id"] == "e1"

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_pull_patterns_offline_falls_back_to_cache(
        self, mock_get_client, temp_db: DataStore
    ):
        # Seed local cache first
        temp_db.cache_patterns([
            {
                "id": "cached-p1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [{"action": "pip_install", "packages": ["pyvisa"]}],
                "confidence_score": 5.0,
            },
        ])
        temp_db.cache_errors([
            {
                "id": "cached-e1",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "error_fingerprint": "fp_cached",
                "success_rate": 0.8,
            },
        ])

        # Supabase client unavailable
        mock_get_client.return_value = None

        ck = CommunityKnowledge(store=temp_db)
        result = ck.pull_patterns("rigol_ds1054z", "linux")

        assert result is not None
        assert len(result["patterns"]) == 1
        assert result["patterns"][0]["id"] == "cached-p1"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["id"] == "cached-e1"
        assert result["working_configs"] == []

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_pull_patterns_offline_no_cache_returns_none(
        self, mock_get_client, temp_db: DataStore
    ):
        mock_get_client.return_value = None
        ck = CommunityKnowledge(store=temp_db)
        result = ck.pull_patterns("rigol_ds1054z", "linux")
        assert result is None

    def test_pull_patterns_returns_none_when_disabled(
        self, temp_db: DataStore
    ):
        temp_db.set_config("telemetry", "off")
        ck = CommunityKnowledge(store=temp_db)
        result = ck.pull_patterns("rigol_ds1054z", "linux")
        assert result is None

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_pull_patterns_exception_falls_back_to_cache(
        self, mock_get_client, temp_db: DataStore
    ):
        """If the Supabase query raises, fall back to cached data."""
        temp_db.cache_patterns([
            {
                "id": "fallback-p",
                "device_type": "rigol_ds1054z",
                "os": "linux",
                "steps": [],
                "confidence_score": 3.0,
            },
        ])

        failing_client = MagicMock()
        failing_client.table.side_effect = Exception("network error")
        mock_get_client.return_value = failing_client

        ck = CommunityKnowledge(store=temp_db)
        result = ck.pull_patterns("rigol_ds1054z", "linux")

        assert result is not None
        assert result["patterns"][0]["id"] == "fallback-p"


# ── push_contribution ─────────────────────────────────────────────────


class TestPushContribution:
    """Pushing contributions to Supabase or local queue on failure."""

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_push_contribution_success(
        self, mock_get_client, temp_db: DataStore
    ):
        mock_client = _mock_supabase_client()
        mock_get_client.return_value = mock_client

        ck = CommunityKnowledge(store=temp_db)
        contribution = {"type": "pattern", "device_type": "rigol_ds1054z"}
        result = ck.push_contribution(contribution)

        assert result is True
        # Verify insert was called
        mock_client.table.assert_called_with("contributions")
        # Nothing should be in the upload queue
        assert temp_db.get_pending_uploads() == []

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_push_contribution_offline_queues_locally(
        self, mock_get_client, temp_db: DataStore
    ):
        mock_get_client.return_value = None

        ck = CommunityKnowledge(store=temp_db)
        contribution = {"type": "pattern", "device_type": "rigol_ds1054z"}
        result = ck.push_contribution(contribution)

        assert result is False
        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["payload"] == contribution

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_push_contribution_exception_queues_locally(
        self, mock_get_client, temp_db: DataStore
    ):
        mock_client = _mock_supabase_client(
            insert_side_effect=Exception("server error")
        )
        mock_get_client.return_value = mock_client

        ck = CommunityKnowledge(store=temp_db)
        contribution = {"type": "error", "error_fp": "abc"}
        result = ck.push_contribution(contribution)

        assert result is False
        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["payload"] == contribution

    def test_push_contribution_disabled_returns_false(
        self, temp_db: DataStore
    ):
        temp_db.set_config("telemetry", "off")
        ck = CommunityKnowledge(store=temp_db)
        result = ck.push_contribution({"data": "anything"})
        assert result is False
        assert temp_db.get_pending_uploads() == []


# ── flush_queue ───────────────────────────────────────────────────────


class TestFlushQueue:
    """Flushing the local upload queue to Supabase."""

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_flush_queue_uploads_and_removes(
        self, mock_get_client, temp_db: DataStore
    ):
        # Seed the queue
        temp_db.queue_upload({"type": "pattern", "id": "q1"})
        temp_db.queue_upload({"type": "pattern", "id": "q2"})
        assert len(temp_db.get_pending_uploads()) == 2

        mock_client = _mock_supabase_client()
        mock_get_client.return_value = mock_client

        ck = CommunityKnowledge(store=temp_db)
        ck.flush_queue()

        # All items should have been removed
        assert temp_db.get_pending_uploads() == []

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_flush_queue_increments_attempts_on_failure(
        self, mock_get_client, temp_db: DataStore
    ):
        temp_db.queue_upload({"type": "pattern", "id": "fail-q"})
        assert temp_db.get_pending_uploads()[0]["attempts"] == 0

        mock_client = _mock_supabase_client(
            insert_side_effect=Exception("upload failed")
        )
        mock_get_client.return_value = mock_client

        ck = CommunityKnowledge(store=temp_db)
        ck.flush_queue()

        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["attempts"] == 1

    @patch("hardware_agent.data.community.CommunityKnowledge._get_client")
    def test_flush_queue_offline_does_nothing(
        self, mock_get_client, temp_db: DataStore
    ):
        temp_db.queue_upload({"type": "test"})
        mock_get_client.return_value = None

        ck = CommunityKnowledge(store=temp_db)
        ck.flush_queue()

        # Item still in queue, untouched
        pending = temp_db.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0]["attempts"] == 0

    def test_flush_queue_disabled_does_nothing(self, temp_db: DataStore):
        temp_db.queue_upload({"type": "test"})
        temp_db.set_config("telemetry", "off")

        ck = CommunityKnowledge(store=temp_db)
        ck.flush_queue()

        assert len(temp_db.get_pending_uploads()) == 1
