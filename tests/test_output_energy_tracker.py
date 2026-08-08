"""Regression tests for Issue 14 output-energy continuity."""

import importlib.util
import sys
from types import ModuleType

import pytest
from pathlib import Path
from types import SimpleNamespace


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
    assert tracker.rollover_count == 1

    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(100, "serial")
    assert tracker.update(3, "serial") == (100, "pending_reset")
    assert tracker.update(4, "serial") == (104, "reset")


def test_output_energy_tracker_ignores_an_isolated_lower_reading() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(100, "serial")
    state = tracker.as_dict()

    assert tracker.update(3, "serial") == (100, "pending_reset")
    assert tracker.as_dict() == state
    assert tracker.update(101, "serial") == (101, None)
    assert tracker.rollover_count == 0


def test_output_energy_tracker_confirms_a_repeated_reset_reading() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(100, "serial")

    assert tracker.update(3, "serial") == (100, "pending_reset")
    assert tracker.update(3, "serial") == (103, "reset")
    assert tracker.rollover_count == 0


def test_output_energy_tracker_rejects_inconsistent_reset_confirmation() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(100, "serial")

    assert tracker.update(3, "serial") == (100, "pending_reset")
    assert tracker.update(99, "serial") == (100, "pending_reset")


def test_output_energy_tracker_restores_seed_and_changes_serial() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(
        {"offset_wh": 2**32, "previous_raw_wh": 3, "serial_number": "old"}, 0
    )
    tracker.update(2**32 - 2, "old")
    assert tracker.update(4, "old")[1] == "wrap"
    assert tracker.rollover_count == 1
    assert tracker.update(4, "new")[0] == 4
    assert tracker.rollover_count == 0

    seeded = TRACKER.OutputEnergyTracker.from_storage(None, 1)
    assert seeded.update(3, "serial")[0] == 2**32 + 3
    assert seeded.rollover_count == 1


def test_output_energy_tracker_rollover_persistence_and_legacy_migration() -> None:
    tracker = TRACKER.OutputEnergyTracker.from_storage(None, 0)
    tracker.update(2**32 - 2, "serial")
    tracker.update(3, "serial")
    restored = TRACKER.OutputEnergyTracker.from_storage(tracker.as_dict(), 0)
    assert restored.rollover_count == 1

    legacy = TRACKER.OutputEnergyTracker.from_storage(
        {"offset_wh": 2**32, "previous_raw_wh": 3, "serial_number": "serial"}, 2
    )
    assert legacy.rollover_count == 2


def test_issue_14_sensor_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    registers = (root / "custom_components/apc_modbus/registers_smt_ups.py").read_text()
    catalog = (
        root / "custom_components/apc_modbus/sensor_catalog_unified.py"
    ).read_text()
    config_flow = (root / "custom_components/apc_modbus/config_flow.py").read_text()
    sensor = (root / "custom_components/apc_modbus/sensor.py").read_text()

    assert '"key": "output_energy"' in registers
    assert '"address": 0x0091' in registers
    assert '"scale": 1' in registers
    assert 'key="output_energy_kwh"' in registers
    assert 'key="output_energy_rollover"' in registers
    assert 'name="Output Energy Rollover"' in registers
    assert "EntityCategory.DIAGNOSTIC" in registers
    assert 'register_key="output_energy"' in registers
    assert "suggested_display_precision=3" in registers
    assert "UnitOfEnergy.KILO_WATT_HOUR" in registers
    assert '"key": "output_energy_kwh"' in catalog
    assert '"key": "output_energy_rollover"' in catalog
    assert '"unit": "kWh"' in catalog
    assert 'description.key == "output_energy_rollover"' in sensor
    assert 'coordinator.data.get("output_energy")' in sensor
    assert "CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS" in config_flow
    assert "vol.All(" in config_flow
    assert "vol.Range(min=0)" in config_flow


def test_output_energy_rollover_is_enabled_by_default() -> None:
    root = Path(__file__).resolve().parents[1]
    availability = root / "custom_components/apc_modbus/sensor_availability_unified.py"
    module_spec = importlib.util.spec_from_file_location("availability", availability)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    assert module.is_sensor_enabled_by_default("output_energy_rollover", "smt_ups")
    assert module.is_sensor_enabled_by_default(
        "output_energy_rollover", "smartconnect_ups"
    )


def _load_energy_runtime(monkeypatch: pytest.MonkeyPatch):
    """Load the small coordinator/sensor surfaces without Home Assistant."""
    root = Path(__file__).resolve().parents[1]
    package = ModuleType("energy_runtime")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "energy_runtime", package)

    pymodbus = ModuleType("pymodbus")
    pymodbus_client = ModuleType("pymodbus.client")
    pymodbus_client.ModbusTcpClient = object
    pymodbus_exceptions = ModuleType("pymodbus.exceptions")
    pymodbus_exceptions.ConnectionException = OSError
    pymodbus_exceptions.ModbusException = OSError
    monkeypatch.setitem(sys.modules, "pymodbus", pymodbus)
    monkeypatch.setitem(sys.modules, "pymodbus.client", pymodbus_client)
    monkeypatch.setitem(sys.modules, "pymodbus.exceptions", pymodbus_exceptions)

    homeassistant = ModuleType("homeassistant")
    ha_const = ModuleType("homeassistant.const")
    ha_const.CONF_HOST = "host"
    ha_const.CONF_PORT = "port"
    ha_const.UnitOfEnergy = SimpleNamespace(KILO_WATT_HOUR="kWh")
    ha_core = ModuleType("homeassistant.core")
    ha_core.HomeAssistant = object
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_coordinator = ModuleType("homeassistant.helpers.update_coordinator")

    class Generic:
        @classmethod
        def __class_getitem__(cls, _item):
            return cls

    ha_coordinator.DataUpdateCoordinator = Generic
    ha_coordinator.UpdateFailed = RuntimeError
    ha_storage = ModuleType("homeassistant.helpers.storage")
    ha_storage.Store = Generic
    ha_sensor = ModuleType("homeassistant.components.sensor")

    class SensorDeviceClass:
        ENERGY = "energy"
        ENUM = "enum"

    class SensorEntity:
        pass

    ha_sensor.SensorDeviceClass = SensorDeviceClass
    ha_sensor.SensorEntity = SensorEntity
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_config_entries.ConfigEntry = object
    ha_device_registry = ModuleType("homeassistant.helpers.device_registry")
    ha_device_registry.DeviceInfo = dict
    ha_entity_platform = ModuleType("homeassistant.helpers.entity_platform")
    ha_entity_platform.AddEntitiesCallback = object
    ha_coordinator.CoordinatorEntity = type("CoordinatorEntity", (), {})
    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.const", ha_const)
    monkeypatch.setitem(sys.modules, "homeassistant.core", ha_core)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", ha_helpers)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components", ModuleType("homeassistant.components")
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.sensor", ha_sensor)
    monkeypatch.setitem(sys.modules, "homeassistant.config_entries", ha_config_entries)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.device_registry", ha_device_registry
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_platform", ha_entity_platform
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.update_coordinator", ha_coordinator
    )
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.storage", ha_storage)

    const = ModuleType("energy_runtime.const")
    const.DEFAULT_IDLE_RECONNECT_SECONDS = 0
    const.DEFAULT_PORT = 502
    const.DEFAULT_SCAN_INTERVAL = 10
    const.DOMAIN = "apc_modbus"
    const.APCModbusSensorDescription = object
    const.KEY_COORDINATOR = "coordinator"
    const.SNMP_EXTERNAL_SENSOR_DESCRIPTIONS = []
    const.SNMP_SELF_TEST_SENSOR_DESCRIPTIONS = []
    monkeypatch.setitem(sys.modules, "energy_runtime.const", const)
    device_types = ModuleType("energy_runtime.device_types")
    device_types.APCDeviceType = SimpleNamespace(
        SMT_UPS="smt", SMARTCONNECT_UPS="smartconnect"
    )
    device_types.classify_device_type = lambda *_: None
    device_types.ProbeKind = object
    device_types.ProbeOutcome = object
    monkeypatch.setitem(sys.modules, "energy_runtime.device_types", device_types)
    registers = ModuleType("energy_runtime.registers_smart_ups")
    registers.REGISTERS, registers.REGISTER_BLOCKS, registers.REGISTER_MAP = [], [], {}
    monkeypatch.setitem(sys.modules, "energy_runtime.registers_smart_ups", registers)
    tracker = ModuleType("energy_runtime.output_energy_tracker")
    tracker.OutputEnergyTracker = object
    monkeypatch.setitem(sys.modules, "energy_runtime.output_energy_tracker", tracker)
    snmp = ModuleType("energy_runtime.snmp_helper")
    for name in (
        "detect_external_probe_oids_sync",
        "get_device_metadata_sync",
        "get_external_probe_data_detected_sync",
        "get_self_test_data_sync",
    ):
        setattr(snmp, name, lambda *_: None)
    monkeypatch.setitem(sys.modules, "energy_runtime.snmp_helper", snmp)
    snmp_state = ModuleType("energy_runtime.snmp_state")
    snmp_state.has_usable_metadata = lambda *_: False
    monkeypatch.setitem(sys.modules, "energy_runtime.snmp_state", snmp_state)

    path = root / "custom_components/apc_modbus/coordinator.py"
    spec = importlib.util.spec_from_file_location("energy_runtime.coordinator", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    external = ModuleType("energy_runtime.external_probe_entities")
    external.is_external_probe_entity_available = lambda *_: True
    icons = ModuleType("energy_runtime.icons_unified")
    icons.resolve_sensor_icon = lambda *_: None
    availability = ModuleType("energy_runtime.sensor_availability_unified")
    availability.is_sensor_enabled_by_default = lambda *_: True
    monkeypatch.setitem(sys.modules, "energy_runtime.external_probe_entities", external)
    monkeypatch.setitem(sys.modules, "energy_runtime.icons_unified", icons)
    monkeypatch.setitem(
        sys.modules, "energy_runtime.sensor_availability_unified", availability
    )
    sensor_path = root / "custom_components/apc_modbus/sensor.py"
    sensor_spec = importlib.util.spec_from_file_location(
        "energy_runtime.sensor", sensor_path
    )
    assert sensor_spec and sensor_spec.loader
    sensor_module = importlib.util.module_from_spec(sensor_spec)
    monkeypatch.setitem(sys.modules, sensor_spec.name, sensor_module)
    sensor_spec.loader.exec_module(sensor_module)
    pdu_path = root / "custom_components/apc_modbus/registers_rack_pdu.py"
    pdu_spec = importlib.util.spec_from_file_location(
        "energy_runtime.registers_rack_pdu", pdu_path
    )
    assert pdu_spec and pdu_spec.loader
    pdu_module = importlib.util.module_from_spec(pdu_spec)
    monkeypatch.setitem(sys.modules, pdu_spec.name, pdu_module)
    pdu_spec.loader.exec_module(pdu_module)
    return module.APCModbusCoordinator, sensor_module.APCModbusSensor, pdu_module


def test_pdu_energy_decodes_to_integer_wh(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator, _, pdu = _load_energy_runtime(monkeypatch)
    device_descriptor = next(
        descriptor
        for descriptor in pdu.DEVICE_REGISTERS
        if descriptor["key"] == "device_energy"
    )
    outlet_descriptor = next(
        descriptor
        for descriptor in pdu.generate_outlet_registers(1)
        if descriptor["key"] == "outlet_1_energy"
    )

    assert coordinator._decode_register(None, [0, 123], device_descriptor) == 12_300
    assert coordinator._decode_register(None, [0, 7], outlet_descriptor) == 700


def test_energy_entity_converts_wh_to_kwh_without_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sensor, _ = _load_energy_runtime(monkeypatch)
    entity = SimpleNamespace(
        coordinator=SimpleNamespace(data={"energy": 12_345}),
        entity_description=SimpleNamespace(
            register_key="energy", value_map=None, device_class="energy"
        ),
    )
    assert sensor.native_value.fget(entity) == 12.345


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
                if isinstance(validator, type):
                    if not isinstance(value, validator):
                        raise Invalid("wrong type")
                    result[marker.key] = value
                else:
                    result[marker.key] = validator(value)
            return result

    class All:
        def __init__(self, *validators):
            self.validators = validators

        def __call__(self, value):
            for validator in self.validators:
                if isinstance(validator, type):
                    if not isinstance(value, validator):
                        raise Invalid("wrong type")
                else:
                    value = validator(value)
            return value

    class Range:
        def __init__(self, *, min=None):
            self.min = min

        def __call__(self, value):
            if self.min is not None and value < self.min:
                raise Invalid("below minimum")
            return value

    vol = ModuleType("voluptuous")
    vol.Invalid = Invalid
    vol.Schema = Schema
    vol.All = All
    vol.Range = Range
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

    for value in (-1, 1.5):
        with pytest.raises(invalid):
            schema({**valid, "output_energy_completed_rollovers": value})
