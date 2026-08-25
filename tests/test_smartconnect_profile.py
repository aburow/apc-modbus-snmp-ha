from pathlib import Path


def test_smartconnect_excludes_unsupported_measurements() -> None:
    root = Path(__file__).resolve().parents[1]
    registers = (root / "custom_components/apc_modbus/registers_smt_ups.py").read_text()
    factory = (root / "custom_components/apc_modbus/register_factory.py").read_text()

    for key in (
        "bypass_voltage",
        "bypass_frequency",
        "input_voltage_l2",
        "input_voltage_l3",
        "output_load_percent_l2",
        "output_apparent_power_percent_l2",
        "output_current_l2",
        "output_voltage_l2",
    ):
        assert f'"{key}",' in registers
    assert "SMARTCONNECT_SENSOR_DESCRIPTIONS" in registers
    assert "not in SMARTCONNECT_UNSUPPORTED_SENSOR_KEYS" in registers
    assert 'key="output_energy_kwh"' in registers

    # Unsupported measurements are excluded at the sensor-entity level only.
    # Modbus reads must still use the two large, diagnosed SMT blocks rather
    # than per-register requests: narrow reads around the gaps left by
    # unsupported registers were never validated against SmartConnect
    # firmware, and splitting the read multiplies request count/traffic.
    smartconnect_branch = factory.split(
        "elif device_type == APCDeviceType.SMARTCONNECT_UPS:", 1
    )[1].split("elif device_type ==", 1)[0]
    assert "registers_smt_ups.REGISTER_BLOCKS" in smartconnect_branch
    assert "_build_blocks_from_registers" not in smartconnect_branch


def test_modbus_identity_metadata_is_a_snmp_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    coordinator = (root / "custom_components/apc_modbus/coordinator.py").read_text()
    setup = (root / "custom_components/apc_modbus/__init__.py").read_text()

    for address in ("0x0204", "0x0214", "0x0224", "0x0234"):
        assert address in coordinator
    assert 'self.snmp_availability != "unavailable"' in coordinator
    assert "await coordinator.async_read_modbus_metadata()" in setup


def test_smartconnect_uses_cloud_configuration_url() -> None:
    root = Path(__file__).resolve().parents[1]
    coordinator = (root / "custom_components/apc_modbus/coordinator.py").read_text()

    configuration_url_method = coordinator.split(
        "def get_configuration_url_for_registry", 1
    )[1].split("def set_capabilities", 1)[0]
    assert "APCDeviceType.SMARTCONNECT_UPS" in configuration_url_method
    assert "https://smartconnect.apc.com/dashboard" in configuration_url_method


def test_smartconnect_exposes_the_smt_command_set_for_testing() -> None:
    root = Path(__file__).resolve().parents[1]
    profiles = (root / "custom_components/apc_modbus/device_profiles.py").read_text()

    smartconnect_profile = profiles.split("SMARTCONNECT_UPS_PROFILE =", 1)[1].split(
        "RACK_PDU_PROFILE =", 1
    )[0]
    assert (
        "command_operations=SMT_UPS_PROFILE.command_operations" in smartconnect_profile
    )
