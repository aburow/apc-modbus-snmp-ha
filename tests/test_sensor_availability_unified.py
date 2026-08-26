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
        "snmp_runtime_calibration_status",
    )
    for key in keys:
        assert AVAILABILITY.is_sensor_enabled_by_default(key, "smart_ups")
        assert not AVAILABILITY.is_sensor_enabled_by_default(key, "rack_pdu")


def test_self_test_day_and_time_are_hidden_by_default() -> None:
    for key in ("snmp_self_test_day", "snmp_self_test_time"):
        assert not AVAILABILITY.is_sensor_enabled_by_default(key, "smart_ups")
        assert not AVAILABILITY.is_sensor_enabled_by_default(key, "smt_ups")


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


def test_snmp_self_test_sensors_require_snmp_and_a_supported_ups_family() -> None:
    sensor_source = MODULE_PATH.with_name("sensor.py").read_text()
    setup_source = MODULE_PATH.with_name("__init__.py").read_text()
    assert 'coordinator.snmp_availability == "available"' in sensor_source
    assert 'coordinator.snmp_availability == "available"' in setup_source
    assert "APCDeviceType.SMART_UPS" in sensor_source
    assert "APCDeviceType.SMT_UPS" in sensor_source
    assert "*SNMP_SELF_TEST_SENSOR_DESCRIPTIONS" in sensor_source


def test_runtime_remaining_is_duration_measurement_for_both_ups_maps() -> None:
    for filename in ("const.py", "registers_smart_ups.py", "registers_smt_ups.py"):
        source = MODULE_PATH.with_name(filename).read_text()
        runtime_descriptor = source.split('key="runtime_remaining"', 1)[1][:300]
        assert "device_class=SensorDeviceClass.DURATION" in runtime_descriptor
        assert "state_class=SensorStateClass.MEASUREMENT" in runtime_descriptor
        assert "suggested_unit_of_measurement" in runtime_descriptor


def test_legacy_runtime_remaining_normalizes_minutes_to_native_seconds() -> None:
    source = MODULE_PATH.with_name("registers_smart_ups.py").read_text()
    register = source.split('"key": "runtime_remaining"', 1)[1][:250]
    sensor = source.split('key="runtime_remaining"', 1)[1][:300]
    assert '"scale": 1 / 60' in register
    assert 'native_unit_of_measurement="s"' in sensor
    assert 'suggested_unit_of_measurement="min"' in sensor


def test_smt_runtime_remaining_suggests_minutes_without_scaling_raw_seconds() -> None:
    source = MODULE_PATH.with_name("registers_smt_ups.py").read_text()
    register = source.split('"key": "runtime_remaining"', 1)[1][:200]
    sensor = source.split('key="runtime_remaining"', 1)[1][:300]
    assert '"scale": 1' in register
    assert "native_unit_of_measurement=UnitOfTime.SECONDS" in sensor
    assert "suggested_unit_of_measurement=UnitOfTime.MINUTES" in sensor


def test_smt_efficiency_exposes_percentage_and_status_from_one_register() -> None:
    source = MODULE_PATH.with_name("registers_smt_ups.py").read_text()

    assert '"key": "input_efficiency"' in source
    assert '"address": 0x009A' in source
    assert '"type": "int16"' in source
    assert 'key="ups_efficiency"' in source
    assert 'key="ups_efficiency_status"' in source
    assert "value_transform=_efficiency_percentage" in source
    assert "value_transform=_efficiency_status" in source


def test_smt_efficiency_transformations() -> None:
    source = MODULE_PATH.with_name("registers_smt_ups.py")
    tree = ast.parse(source.read_text())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.FunctionDef))
        and getattr(node, "name", None)
        in {"_efficiency_percentage", "_efficiency_status"}
        or isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "EFFICIENCY_STATUS"
            for target in node.targets
        )
    ]
    namespace: dict[str, object] = {}
    exec(compile(ast.Module(nodes, []), str(source), "exec"), namespace)

    assert namespace["_efficiency_percentage"](12160) == 95
    assert namespace["_efficiency_percentage"](-4) is None
    assert namespace["_efficiency_status"](0) == "Available"
    assert namespace["_efficiency_status"](-6) == "Battery Charging"


def test_smt_status_change_cause_uses_documented_enum() -> None:
    source = MODULE_PATH.with_name("registers_smt_ups.py")
    source_text = source.read_text()
    tree = ast.parse(source_text)
    cause_map = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "UPS_STATUS_CHANGE_CAUSES"
            for target in node.targets
        )
    )

    assert cause_map == dict(
        enumerate(
            (
                "System Initialization",
                "High Input Voltage",
                "Low Input Voltage",
                "Distorted Input",
                "Rapid Change of Input Voltage",
                "High Input Frequency",
                "Low Input Frequency",
                "Frequency and/or Phase Difference",
                "Acceptable Input",
                "Automatic Test",
                "Test Ended",
                "Local UI Command",
                "Protocol Command",
                "Low Battery Voltage",
                "General Error",
                "Power System Error",
                "Battery System Error",
                "Error Cleared",
                "Automatic Restart",
                "Distorted Inverter Output",
                "Inverter Output Acceptable",
                "EPO Interface",
                "Input Phase Delta Out of Range",
                "Input Neutral Not Connected",
                "ATS Transfer",
                "Configuration Change",
                "Alert Asserted",
                "Alert Cleared",
                "Plug Rating Exceeded",
                "Outlet Group State Change",
                "Failure Bypass Expired",
            )
        )
    )
    assert '"key": "ups_status_change_cause"' in source_text
    assert '"address": 0x0002' in source_text
    assert (
        '"registers": [0x0000, 0x0002, 0x0012, 0x0013, 0x0014, 0x0016]' in source_text
    )
    assert 'key="ups_status_change_cause"' in source_text
    assert "value_map=UPS_STATUS_CHANGE_CAUSES" in source_text


def test_smt_shutdown_imminent_uses_simple_signaling_status_bit_one() -> None:
    source = MODULE_PATH.with_name("registers_smt_ups.py").read_text()

    assert '"key": "simple_signaling_status_bf"' in source
    assert '"address": 0x0012' in source
    assert '"registers": [0x0000, 0x0002, 0x0012, 0x0013, 0x0014, 0x0016]' in source
    shutdown_imminent = source.split('key="ups_shutdown_imminent"', 1)[1][:350]
    assert 'name="Shutdown Imminent"' in shutdown_imminent
    assert "device_class=BinarySensorDeviceClass.PROBLEM" in shutdown_imminent
    assert 'register_key="simple_signaling_status_bf"' in shutdown_imminent
    assert "bit_index=1" in shutdown_imminent


def test_ups_on_battery_uses_power_device_class_for_all_ups_maps() -> None:
    for filename in ("const.py", "registers_smart_ups.py", "registers_smt_ups.py"):
        source = MODULE_PATH.with_name(filename).read_text()
        on_battery = source.split('key="ups_on_battery"', 1)[1][:250]
        assert "device_class=BinarySensorDeviceClass.POWER" in on_battery
