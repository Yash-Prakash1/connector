"""Community knowledge client — Supabase communication with graceful offline."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from hardware_agent.data.store import DataStore

logger = logging.getLogger(__name__)

# Public anon key — safe to embed. RLS policies protect data.
_DEFAULT_URL = "https://fgqadwrjnxcufcpthlpd.supabase.co"
_DEFAULT_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZncWFkd3JqbnhjdWZjcHRobHBkIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3NzE1NjQzNjMsImV4cCI6MjA4NzE0MDM2M30."
    "QTqRvjBGaUFP8HmFFZhTP-eI7tEt-1B35R4fTZ7lQEw"
)


def _resolve_credentials(
    store: DataStore,
) -> tuple[Optional[str], Optional[str]]:
    """Resolve Supabase credentials: env var → config DB → embedded defaults."""
    url = (
        os.environ.get("HARDWARE_AGENT_SUPABASE_URL")
        or store.get_config("supabase-url")
        or _DEFAULT_URL
    )
    key = (
        os.environ.get("HARDWARE_AGENT_SUPABASE_KEY")
        or store.get_config("supabase-key")
        or _DEFAULT_KEY
    )
    return url, key


class CommunityKnowledge:
    """Handles all Supabase communication with graceful offline fallback."""

    def __init__(
        self,
        store: DataStore,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
    ):
        self.store = store
        if supabase_url and supabase_key:
            self.supabase_url = supabase_url
            self.supabase_key = supabase_key
        else:
            self.supabase_url, self.supabase_key = _resolve_credentials(store)
        self._client: Any = None

    @property
    def is_configured(self) -> bool:
        """True when both Supabase URL and key are available."""
        return self.supabase_url is not None and self.supabase_key is not None

    def _get_client(self) -> Any:
        """Lazy-initialize Supabase client."""
        if not self.is_configured:
            return None
        if self._client is None:
            try:
                from supabase import create_client

                self._client = create_client(
                    self.supabase_url, self.supabase_key
                )
            except Exception as e:
                logger.debug("Failed to create Supabase client: %s", e)
                return None
        return self._client

    def is_enabled(self) -> bool:
        """Check if telemetry/community sharing is enabled."""
        val = self.store.get_config("telemetry")
        return val != "false" and val != "off"

    def pull_patterns(
        self, device_type: str, os_name: str
    ) -> Optional[dict]:
        """Pull community patterns from Supabase. Falls back to cache."""
        if not self.is_enabled():
            return None

        client = self._get_client()
        if client is None:
            return self._get_cached_data(device_type, os_name)

        try:
            # Pull resolution patterns
            patterns_resp = (
                client.table("resolution_patterns")
                .select("*")
                .eq("device_type", device_type)
                .eq("os", os_name)
                .order("confidence_score", desc=True)
                .limit(10)
                .execute()
            )
            patterns = patterns_resp.data or []
            if patterns:
                self.store.cache_patterns(patterns)

            # Pull error resolutions
            errors_resp = (
                client.table("error_resolutions")
                .select("*")
                .or_(
                    f"device_type.eq.{device_type},device_type.is.null"
                )
                .or_(f"os.eq.{os_name},os.is.null")
                .order("success_rate", desc=True)
                .limit(20)
                .execute()
            )
            errors = errors_resp.data or []
            if errors:
                self.store.cache_errors(errors)

            # Pull working configs
            configs_resp = (
                client.table("working_configurations")
                .select("*")
                .eq("device_type", device_type)
                .eq("os", os_name)
                .order("verified_count", desc=True)
                .limit(5)
                .execute()
            )
            configs = configs_resp.data or []

            return {
                "patterns": patterns,
                "errors": errors,
                "working_configs": configs,
            }

        except Exception as e:
            logger.warning("Failed to pull from Supabase: %s", e)
            return self._get_cached_data(device_type, os_name)

    def push_contribution(self, contribution: dict) -> bool:
        """Push an anonymized contribution to Supabase."""
        if not self.is_enabled():
            return False

        client = self._get_client()
        if client is None:
            self.store.queue_upload(contribution)
            return False

        try:
            client.table("contributions").insert(contribution).execute()
            return True
        except Exception as e:
            logger.warning("Failed to push contribution: %s", e)
            self.store.queue_upload(contribution)
            return False

    def flush_queue(self) -> None:
        """Try to upload any pending items from the upload queue."""
        if not self.is_enabled():
            return

        client = self._get_client()
        if client is None:
            return

        pending = self.store.get_pending_uploads()
        for item in pending:
            try:
                client.table("contributions").insert(
                    item["payload"]
                ).execute()
                self.store.remove_upload(item["id"])
            except Exception as e:
                logger.debug("Failed to flush upload %s: %s", item["id"], e)
                self.store.increment_upload_attempts(item["id"])

    def _get_cached_data(
        self, device_type: str, os_name: str
    ) -> Optional[dict]:
        """Return cached community data from local SQLite."""
        patterns = self.store.get_cached_patterns(device_type, os_name)
        errors = self.store.get_cached_errors(device_type, os_name)
        if not patterns and not errors:
            return None
        return {
            "patterns": patterns,
            "errors": errors,
            "working_configs": [],
        }
