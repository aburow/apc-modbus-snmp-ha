"""Regression tests for Issue 14 output-energy continuity."""

import importlib.util
import sys
from types import ModuleType

import pytest
from pathlib import Path


def _load_tracker():
    path = Path(__file__).resolve().parents[1] / (
        "custom_components/apc_modbus/output_energy_tracker.py"
    )
    spec = importlib.util.spec_from_file_location("output_energy_tracker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TRACKER = _load_tracker()


def test_output_energy_tracker_continuity() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    assert tracker.update(10, "serial")[0] == 10
    assert tracker.update(12, "serial")[0] == 12

    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(2**32 - 2, "serial")
    assert tracker.update(3, "serial") == (2**32 + 3, "wrap")

    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(100, "serial")
    assert tracker.update(3, "serial") == (103, "reset")


def test_output_energy_tracker_restores_seed_and_changes_serial() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(
        {"offset_wh": 2**32, "previous_raw_wh": 3, "serial_number": "old"}, 0
    )
    assert tracker.update(4, "old")[0] == 2**32 + 4
    assert tracker.update(4, "new")[0] == 4

    seeded = TRACKER.OutputEnergyTracker.from_storage(None, 1)
    assert seeded.update(3, "serial")[0] == 2**32 + 3


def test_issue_14_sensor_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    registers = (root / "custom_components/apc_modbus/registers_smt_ups.py").read_text()
    catalog = (
        root / "custom_components/apc_modbus/sensor_catalog_unified.py"
    ).read_text()
    config_flow = (root / "custom_components/apc_modbus/config_flow.py").read_text()

    assert '"key": "output_energy"' in registers
    assert '"address": 0x0091' in registers
    assert '"scale": 1' in registers
    assert 'key="output_energy_kwh"' in registers
    assert 'register_key="output_energy_kwh"' in registers
    assert "UnitOfEnergy.KILO_WATT_HOUR" in registers
    assert '"key": "output_energy_kwh"' in catalog
    assert '"unit": "kWh"' in catalog
    assert "CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS" in config_flow
    assert "_non_negative_integer" in config_flow


def _load_config_flow_schema(monkeypatch: pytest.MonkeyPatch):
    """Load the config schema with the tiny HA/voluptuous surface it uses."""

    class Invalid(Exception):
        pass

    class Marker:
        def __init__(self, key, default=None, required=False):
            self.key = key
            self.default = default
            self.required = required

    class Schema:
        def __init__(self, fields):
            self.fields = fields

        def __call__(self, values):
            result = {}
            for marker, validator in self.fields.items():
                if marker.key not in values:
                    if marker.required:
                        raise Invalid("required")
                    value = marker.default
                else:
                    value = values[marker.key]
                result[marker.key] = validator(value)
            return result

    vol = ModuleType("voluptuous")
    vol.Invalid = Invalid
    vol.Schema = Schema
    vol.Required = lambda key, default=None: Marker(key, default, required=True)
    vol.Optional = lambda key, default=None: Marker(key, default)
    monkeypatch.setitem(sys.modules, "voluptuous", vol)

    homeassistant = ModuleType("homeassistant")
    config_entries = ModuleType("homeassistant.config_entries")

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    config_entries.ConfigFlow = ConfigFlow
    homeassistant.config_entries = config_entries
    ha_const = ModuleType("homeassistant.const")
    ha_const.CONF_HOST = "host"
    ha_const.CONF_PORT = "port"
    ha_const.CONF_SCAN_INTERVAL = "scan_interval"
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.config_entries", config_entries)
    monkeypatch.setitem(sys.modules, "homeassistant.const", ha_const)

    package = ModuleType("issue14_config")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "issue14_config", package)
    const = ModuleType("issue14_config.const")
    for key, value in {
        "CONF_DEVICE_NAME": "device_name",
        "CONF_KEEP_CONNECTION_OPEN": "keep_connection_open",
        "CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS": "output_energy_completed_rollovers",
        "CONF_SNMP_COMMUNITY": "snmp_community",
        "CONF_SNMP_PORT": "snmp_port",
        "CONF_UNIT": "unit",
        "DEFAULT_KEEP_CONNECTION_OPEN": False,
        "DEFAULT_NAME": "APC UPS",
        "DEFAULT_PORT": 502,
        "DEFAULT_SCAN_INTERVAL": 10,
        "DEFAULT_SNMP_COMMUNITY": "public",
        "DEFAULT_SNMP_PORT": 161,
        "DEFAULT_UNIT": 1,
        "DOMAIN": "apc_modbus",
    }.items():
        setattr(const, key, value)
    monkeypatch.setitem(sys.modules, "issue14_config.const", const)

    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components/apc_modbus/config_flow.py"
    )
    spec = importlib.util.spec_from_file_location("issue14_config.config_flow", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module.DATA_SCHEMA, Invalid


def test_data_schema_rejects_invalid_output_energy_rollover_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema, invalid = _load_config_flow_schema(monkeypatch)
    valid = {"host": "ups", "snmp_community": "public"}
    assert schema(valid)["output_energy_completed_rollovers"] == 0

    for value in (-1, 1.5, True):
        with pytest.raises(invalid):
            schema({**valid, "output_energy_completed_rollovers": value})
