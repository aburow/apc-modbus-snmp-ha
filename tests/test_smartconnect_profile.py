from pathlib import Path


def test_smartconnect_excludes_unsupported_measurements() -> None:
    root = Path(__file__).resolve().parents[1]
    registers = (root / "custom_components/apc_modbus/registers_smt_ups.py").read_text()
    factory = (root / "custom_components/apc_modbus/register_factory.py").read_text()

    for key in (
        "output_energy",
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
    assert "not in registers_smt_ups.SMARTCONNECT_UNSUPPORTED_REGISTER_KEYS" in factory


def test_modbus_identity_metadata_is_a_snmp_fallback() -> None:
    root = Path(__file__).resolve().parents[1]
    coordinator = (root / "custom_components/apc_modbus/coordinator.py").read_text()
    setup = (root / "custom_components/apc_modbus/__init__.py").read_text()

    for address in ("0x0204", "0x0214", "0x0224", "0x0234"):
        assert address in coordinator
    assert 'self.snmp_availability != "unavailable"' in coordinator
    assert "await coordinator.async_read_modbus_metadata()" in setup
