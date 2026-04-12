import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "apc_modbus"
    / "device_info_unified.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "apc_device_info_unified",
    MODULE_PATH,
)
assert MODULE_SPEC and MODULE_SPEC.loader
DEVICE_INFO = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DEVICE_INFO)


def test_import_outside_homeassistant_runtime() -> None:
    assert DEVICE_INFO.CONTRACT_VERSION == "1.0"
    assert callable(DEVICE_INFO.resolve_device_info)


def test_resolve_device_info_with_representative_payload() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "model": "Smart-UPS 1500",
            "firmware_version": "UPS 08.1 (ID1003)",
            "firmware_date": "08/03/2024",
            "serial_number": "AS2431136618",
            "host": "192.168.100.7",
        },
        "apc_modbus_smt",
    )
    assert result == {
        "manufacturer": "APC",
        "model": "Smart-UPS 1500",
        "sw_version": "UPS 08.1 (ID1003)",
        "hw_version": "08/03/2024",
        "serial_number": "AS2431136618",
        "configuration_url": "http://192.168.100.7",
    }


def test_empty_or_unknown_input_returns_subset_only() -> None:
    assert DEVICE_INFO.resolve_device_info({}, "apc_modbus_smart") == {
        "manufacturer": "APC"
    }
    assert (
        DEVICE_INFO.resolve_device_info(
            {"model": "unknown", "serial_number": "  "},
            "unknown_source",
        )
        == {}
    )


def test_only_canonical_keys_and_non_blank_values_returned() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "model": "Smart-UPS 3000",
            "serial_number": "AS2038264450",
            "extra_field": "must_not_appear",
            "configuration_url": "https://192.168.1.10",
        },
        "apc_modbus_smart",
    )
    assert set(result).issubset(DEVICE_INFO.CANONICAL_DEVICE_INFO_KEYS)
    assert all(isinstance(value, str) and value.strip() for value in result.values())


def test_malformed_input_never_raises() -> None:
    assert DEVICE_INFO.resolve_device_info(None, "apc_modbus_smart") == {}
    assert DEVICE_INFO.resolve_device_info(123, "apc_modbus_smart") == {}
    assert (
        DEVICE_INFO.resolve_device_info(["not", "a", "dict"], "apc_modbus_smart") == {}
    )
