"""Tests for hardware_agent.data.fingerprint — initial state fingerprinting."""

from __future__ import annotations

import copy

import pytest

from hardware_agent.core.models import OS, Environment
from hardware_agent.data.fingerprint import fingerprint_initial_state


# ── Fingerprint determinism and sensitivity ───────────────────────────


class TestFingerprintInitialState:
    """Fingerprint should be deterministic and sensitive to relevant state."""

    def test_same_env_same_device_same_fingerprint(self, mock_environment):
        fp1 = fingerprint_initial_state(mock_environment, "rigol_ds1054z")
        fp2 = fingerprint_initial_state(mock_environment, "rigol_ds1054z")
        assert fp1 == fp2

    def test_different_device_type_different_fingerprint(
        self, mock_environment
    ):
        fp1 = fingerprint_initial_state(mock_environment, "rigol_ds1054z")
        fp2 = fingerprint_initial_state(mock_environment, "rigol_dp832")
        assert fp1 != fp2

    def test_different_packages_different_fingerprint(self, mock_environment):
        env_with_pyvisa = copy.deepcopy(mock_environment)
        env_with_pyvisa.installed_packages["pyvisa"] = "1.14.0"

        fp_without = fingerprint_initial_state(
            mock_environment, "rigol_ds1054z"
        )
        fp_with = fingerprint_initial_state(
            env_with_pyvisa, "rigol_ds1054z"
        )
        assert fp_without != fp_with

    def test_different_os_different_fingerprint(self, mock_environment):
        env_macos = copy.deepcopy(mock_environment)
        env_macos.os = OS.MACOS

        fp_linux = fingerprint_initial_state(
            mock_environment, "rigol_ds1054z"
        )
        fp_macos = fingerprint_initial_state(env_macos, "rigol_ds1054z")
        assert fp_linux != fp_macos

    def test_usb_device_presence_affects_fingerprint(self, mock_environment):
        """mock_environment has a Rigol 1ab1 USB device; removing it changes the fp."""
        fp_with_usb = fingerprint_initial_state(
            mock_environment, "rigol_ds1054z"
        )

        env_no_usb = copy.deepcopy(mock_environment)
        env_no_usb.usb_devices = []

        fp_no_usb = fingerprint_initial_state(env_no_usb, "rigol_ds1054z")
        assert fp_with_usb != fp_no_usb

    def test_fingerprint_is_16_char_hex(self, mock_environment):
        fp = fingerprint_initial_state(mock_environment, "rigol_ds1054z")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_irrelevant_packages_dont_change_fingerprint(
        self, mock_environment
    ):
        """Only RELEVANT_PACKAGES matter; other packages are ignored."""
        env_extra = copy.deepcopy(mock_environment)
        env_extra.installed_packages["requests"] = "2.31.0"

        fp_base = fingerprint_initial_state(
            mock_environment, "rigol_ds1054z"
        )
        fp_extra = fingerprint_initial_state(env_extra, "rigol_ds1054z")
        assert fp_base == fp_extra

    def test_visa_resources_affect_fingerprint(self, mock_environment):
        """visa_available flag changes when resources present."""
        env_with_visa = copy.deepcopy(mock_environment)
        env_with_visa.visa_resources = ["USB0::0x1AB1::0x04CE::DS1ZA1::INSTR"]

        fp_no_visa = fingerprint_initial_state(
            mock_environment, "rigol_ds1054z"
        )
        fp_with_visa = fingerprint_initial_state(
            env_with_visa, "rigol_ds1054z"
        )
        assert fp_no_visa != fp_with_visa

    def test_empty_environment(self, mock_environment_empty):
        """Fingerprinting works even with an empty environment."""
        fp = fingerprint_initial_state(
            mock_environment_empty, "rigol_ds1054z"
        )
        assert isinstance(fp, str)
        assert len(fp) == 16
