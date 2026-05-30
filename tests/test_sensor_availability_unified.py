import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "sensor_availability_unified.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "apc_sensor_availability_unified", MODULE_PATH
)
assert MODULE_SPEC and MODULE_SPEC.loader
AVAILABILITY = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AVAILABILITY)


def test_ups_core_sensor_keys_enabled_by_default() -> None:
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("runtime_remaining", "smart_ups")
        is True
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("battery_state_of_charge", "smt_ups")
        is True
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("output_voltage", "smt_ups") is True
    )


def test_non_core_ups_sensor_keys_disabled_by_default() -> None:
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("snmp_external_temp_1", "smart_ups")
        is True
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("battery_temperature", "smt_ups")
        is False
    )


def test_non_primary_phase_ups_sensor_keys_disabled_by_default() -> None:
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("output_voltage_l2", "smt_ups")
        is False
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("input_voltage_l3", "smt_ups")
        is False
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("output_load_percent_l2", "smart_ups")
        is False
    )


def test_rack_pdu_core_enabled_and_non_core_disabled_by_default() -> None:
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("device_real_power", "rack_pdu")
        is True
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("phase_l1_voltage", "rack_pdu")
        is True
    )
    assert (
        AVAILABILITY.is_sensor_enabled_by_default("outlet_1_current", "rack_pdu")
        is False
    )
    assert (
        AVAILABILITY.is_binary_sensor_enabled_by_default("bank_1_alarm", "rack_pdu")
        is False
    )


def test_entity_enabled_default_contract_api() -> None:
    assert AVAILABILITY.entity_enabled_default("output_voltage") is True
    assert AVAILABILITY.entity_enabled_default("ups_on_battery") is True
    assert AVAILABILITY.entity_enabled_default("battery_temperature") is False
    assert AVAILABILITY.entity_enabled_default("unknown_metric_key") is False
    assert AVAILABILITY.entity_enabled_default(None) is True
