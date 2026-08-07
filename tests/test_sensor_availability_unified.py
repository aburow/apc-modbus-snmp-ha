import ast
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


def test_self_test_sensors_are_enabled_only_for_ups_families() -> None:
    keys = (
        "snmp_self_test_schedule",
        "snmp_self_test_result",
        "snmp_last_self_test_date",
        "snmp_self_test_time",
        "snmp_self_test_day",
        "snmp_runtime_calibration_status",
    )
    for key in keys:
        assert AVAILABILITY.is_sensor_enabled_by_default(key, "smart_ups")
        assert not AVAILABILITY.is_sensor_enabled_by_default(key, "rack_pdu")


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


def test_runtime_calibration_sensor_has_human_readable_enum_states() -> None:
    const_path = MODULE_PATH.with_name("const.py")
    tree = ast.parse(const_path.read_text())
    descriptions = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "SNMP_SELF_TEST_SENSOR_DESCRIPTIONS"
            for target in node.targets
        )
    )
    calibration = next(
        node
        for node in descriptions.elts
        if isinstance(node, ast.Call)
        and any(
            keyword.arg == "key"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "snmp_runtime_calibration_status"
            for keyword in node.keywords
        )
    )
    value_map = ast.literal_eval(
        next(
            keyword.value
            for keyword in calibration.keywords
            if keyword.arg == "value_map"
        )
    )

    assert value_map == {
        1: "Calibration Complete",
        2: "Cannot Calibrate — Battery Not Fully Charged",
        3: "Calibration In Progress",
        4: "Calibration Refused",
        5: "Calibration Aborted",
        6: "Calibration Pending",
    }


def test_runtime_calibration_unknown_codes_use_sensor_fallback() -> None:
    sensor_source = MODULE_PATH.with_name("sensor.py").read_text()
    assert 'value_map.get(code, f"Unknown ({code})")' in sensor_source


def test_runtime_calibration_sensor_is_added_only_for_ups_families() -> None:
    sensor_source = MODULE_PATH.with_name("sensor.py").read_text()
    assert "APCDeviceType.SMART_UPS, APCDeviceType.SMT_UPS" in sensor_source
    assert "*SNMP_SELF_TEST_SENSOR_DESCRIPTIONS" in sensor_source
