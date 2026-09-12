"""Regression coverage for documented SMT battery bitfields."""

import ast
from pathlib import Path


MODULE = (
    Path(__file__).resolve().parents[1]
    / "custom_components/apc_modbus/registers_smt_ups.py"
)


def _keyword_values(call: ast.Call) -> dict[str, object]:
    return {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in call.keywords
        if keyword.arg in {"key", "register_key", "bit_index"}
    }


def _binary_bitfields() -> dict[str, tuple[str, int]]:
    tree = ast.parse(MODULE.read_text())
    descriptions = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "BINARY_SENSOR_DESCRIPTIONS"
    )
    assert isinstance(descriptions, ast.List)
    return {
        values["key"]: (values["register_key"], values["bit_index"])
        for node in descriptions.elts
        if isinstance(node, ast.Call)
        if (values := _keyword_values(node)).get("register_key")
        in {"battery_lifetime_status_bf", "battery_system_error_bf"}
    }


def test_smt_battery_bitfields_use_the_documented_independent_masks() -> None:
    actual = _binary_bitfields()
    expected = {
        "battery_lifetime_ok": ("battery_lifetime_status_bf", 0),
        "battery_lifetime_near_end": ("battery_lifetime_status_bf", 1),
        "battery_lifetime_exceeded": ("battery_lifetime_status_bf", 2),
        "battery_lifetime_near_end_acknowledged": (
            "battery_lifetime_status_bf",
            3,
        ),
        "battery_lifetime_exceeded_acknowledged": (
            "battery_lifetime_status_bf",
            4,
        ),
        "battery_measured_lifetime_near_end": (
            "battery_lifetime_status_bf",
            5,
        ),
        "battery_measured_lifetime_near_end_acknowledged": (
            "battery_lifetime_status_bf",
            6,
        ),
        "battery_disconnected": ("battery_system_error_bf", 0),
        "battery_overvoltage": ("battery_system_error_bf", 1),
        "battery_needs_replacement": ("battery_system_error_bf", 2),
        "battery_overtemperature_critical": ("battery_system_error_bf", 3),
        "battery_charger_fault": ("battery_system_error_bf", 4),
        "battery_temperature_sensor_fault": ("battery_system_error_bf", 5),
        "battery_bus_soft_start_fault": ("battery_system_error_bf", 6),
        "battery_overtemperature": ("battery_system_error_bf", 7),
        "battery_general_error": ("battery_system_error_bf", 8),
        "battery_communication_error": ("battery_system_error_bf", 9),
        "battery_disconnected_frame": ("battery_system_error_bf", 10),
        "battery_firmware_mismatch": ("battery_system_error_bf", 11),
        "battery_voltage_sense_error": ("battery_system_error_bf", 12),
        "battery_incompatible_pack": ("battery_system_error_bf", 13),
    }

    assert actual == expected
    for register_key in {register_key for register_key, _ in expected.values()}:
        bits = [
            bit for key, (source, bit) in expected.items() if source == register_key
        ]
        for bit in bits:
            assert bool((1 << bit) & (1 << bit))
            assert all(
                not ((1 << other) & (1 << bit)) for other in bits if other != bit
            )


def test_smt_status_block_reads_battery_lifetime_status() -> None:
    source = MODULE.read_text()

    assert '"key": "battery_lifetime_status_bf"' in source
    assert '"address": 0x0019' in source
    assert '"count": 26' in source
    assert (
        '"registers": [0x0000, 0x0002, 0x0012, 0x0013, 0x0014, 0x0016, 0x0019]'
        in source
    )
