"""Tests for hardware_agent.devices.registry — auto-discovery and lookup."""

from __future__ import annotations

import pytest

from hardware_agent.devices import registry
from hardware_agent.devices.base import DeviceModule
from hardware_agent.devices.rigol_ds1054z.module import RigolDS1054ZModule


class TestListModules:
    def setup_method(self):
        registry._reset()

    def test_list_modules_finds_rigol(self):
        modules = registry.list_modules()
        assert "rigol_ds1054z" in modules

    def test_list_modules_returns_list_of_strings(self):
        modules = registry.list_modules()
        assert isinstance(modules, list)
        assert all(isinstance(m, str) for m in modules)

    def test_list_modules_not_empty(self):
        modules = registry.list_modules()
        assert len(modules) >= 1


class TestGetModule:
    def setup_method(self):
        registry._reset()

    def test_get_rigol_module(self):
        module = registry.get_module("rigol_ds1054z")
        assert isinstance(module, RigolDS1054ZModule)

    def test_get_module_returns_device_module(self):
        module = registry.get_module("rigol_ds1054z")
        assert isinstance(module, DeviceModule)

    def test_get_module_info_matches(self):
        module = registry.get_module("rigol_ds1054z")
        info = module.get_info()
        assert info.identifier == "rigol_ds1054z"
        assert info.name == "Rigol DS1054Z"

    def test_get_module_unknown_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown device"):
            registry.get_module("nonexistent_device_xyz")

    def test_get_module_unknown_message_contains_available(self):
        with pytest.raises(ValueError, match="rigol_ds1054z"):
            registry.get_module("bad_id")


class TestDetectDevice:
    def setup_method(self):
        registry._reset()

    def test_detect_rigol_usb(self):
        usb = ["Bus 001 Device 003: ID 1ab1:04ce Rigol Technologies DS1054Z"]
        result = registry.detect_device(usb, [])
        assert result is not None
        assert isinstance(result, RigolDS1054ZModule)

    def test_detect_rigol_visa(self):
        visa = ["USB0::1AB1::04CE::DS1ZA000000001::INSTR"]
        result = registry.detect_device([], visa)
        assert result is not None
        assert result.get_info().identifier == "rigol_ds1054z"

    def test_detect_returns_none_no_match(self):
        usb = ["Bus 001 Device 003: ID ffff:0000 Unknown Device"]
        visa = ["GPIB0::1::INSTR"]
        result = registry.detect_device(usb, visa)
        assert result is None

    def test_detect_empty_lists_returns_none(self):
        result = registry.detect_device([], [])
        assert result is None

    def test_detect_returns_device_module_instance(self):
        usb = ["Bus 001 Device 003: ID 1ab1:04ce Rigol Technologies DS1054Z"]
        result = registry.detect_device(usb, [])
        assert isinstance(result, DeviceModule)


class TestReset:
    def test_reset_clears_registry(self):
        # Trigger discovery first
        registry.list_modules()
        assert len(registry._registry) > 0

        registry._reset()
        assert len(registry._registry) == 0
        assert registry._discovered is False

    def test_rediscovery_after_reset(self):
        registry.list_modules()
        registry._reset()
        # After reset, list_modules should re-discover
        modules = registry.list_modules()
        assert "rigol_ds1054z" in modules


class TestDiscoveryIdempotent:
    def setup_method(self):
        registry._reset()

    def test_multiple_calls_same_result(self):
        first = registry.list_modules()
        second = registry.list_modules()
        assert first == second

    def test_get_module_same_instance(self):
        """Multiple calls return the same cached instance."""
        a = registry.get_module("rigol_ds1054z")
        b = registry.get_module("rigol_ds1054z")
        assert a is b
