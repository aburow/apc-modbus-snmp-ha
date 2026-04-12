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


def test_resolve_device_info_smart_profile() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "model": "Smart-UPS 700",
            "firmware": "50.14.I",
            "firmware_date": "06/05/02",
            "serial_number": "QS0223111264",
            "host": "192.168.100.3",
        },
        "apc_modbus_smart",
    )
    assert result == {
        "manufacturer": "APC",
        "model": "Smart-UPS 700",
        "sw_version": "50.14.I",
        "hw_version": "06/05/02",
        "serial_number": "QS0223111264",
        "configuration_url": "http://192.168.100.3",
    }


def test_resolve_device_info_smt_profile() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "model": "Smart-UPS X 3000",
            "firmware_version": "UPS 08.1 (ID1003)",
            "firmware_date": "08/03/2024",
            "serial_number": "AS2431136618",
            "host": "192.168.100.7",
        },
        "apc_modbus_smt",
    )
    assert result == {
        "manufacturer": "APC",
        "model": "Smart-UPS X 3000",
        "sw_version": "UPS 08.1 (ID1003)",
        "hw_version": "08/03/2024",
        "serial_number": "AS2431136618",
        "configuration_url": "http://192.168.100.7",
    }


def test_resolve_device_info_rack_pdu_profile() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "model": "AP8858",
            "firmware_version": "v7.1.4",
            "firmware_date": "07/14/2012",
            "serial_number": "5A1229E06611",
            "configuration_url": "https://192.168.100.117",
        },
        "apc_modbus_rack_pdu",
    )
    assert result == {
        "manufacturer": "APC",
        "model": "AP8858",
        "sw_version": "v7.1.4",
        "hw_version": "07/14/2012",
        "serial_number": "5A1229E06611",
        "configuration_url": "https://192.168.100.117",
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


def test_unknown_markers_are_dropped() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "manufacturer": "unknown",
            "model": "n/a",
            "firmware": "NA",
            "firmware_date": "unavailable",
            "serial_number": "none",
            "configuration_url": "http://",
            "host": "  ",
        },
        "apc_modbus_smart",
    )
    assert result == {"manufacturer": "APC"}


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
