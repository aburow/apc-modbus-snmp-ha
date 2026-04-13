import importlib.util
from pathlib import Path


def _load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    module_spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


ICONS = _load_module(
    "apc_icons_unified", "custom_components/apc_modbus/icons_unified.py"
)
AVAILABILITY = _load_module(
    "apc_sensor_availability_unified",
    "custom_components/apc_modbus/sensor_availability_unified.py",
)
DEVICE_INFO = _load_module(
    "apc_device_info_unified",
    "custom_components/apc_modbus/device_info_unified.py",
)
CAP_PROFILES = _load_module(
    "apc_capability_profiles_unified",
    "custom_components/apc_modbus/capability_profiles_unified.py",
)


def test_interface_modules_import_in_plain_python() -> None:
    assert callable(ICONS.resolve_sensor_icon)
    assert callable(AVAILABILITY.entity_enabled_default)
    assert callable(DEVICE_INFO.resolve_device_info)
    assert CAP_PROFILES.CONTRACT_VERSION == "2.0.0"


def test_contract_functions_never_raise() -> None:
    assert isinstance(ICONS.resolve_sensor_icon("battery_capacity"), str)
    assert isinstance(ICONS.resolve_sensor_icon(None), str)
    assert isinstance(AVAILABILITY.entity_enabled_default("runtime_remaining"), bool)
    assert isinstance(AVAILABILITY.entity_enabled_default(None), bool)
    result = DEVICE_INFO.resolve_device_info(
        {"model": "Smart-UPS 700"}, "apc_modbus_smart"
    )
    assert isinstance(result, dict)
    assert DEVICE_INFO.resolve_device_info(None, "apc_modbus_smart") == {}


def test_device_info_never_returns_blank_or_invalid_keys() -> None:
    result = DEVICE_INFO.resolve_device_info(
        {
            "manufacturer": "APC",
            "model": "Smart-UPS 3000",
            "serial_number": "AS2038264450",
            "firmware": "UPS 18.0",
            "configuration_url": "https://192.168.100.7",
        },
        "apc_modbus_smart",
    )
    assert set(result).issubset(DEVICE_INFO.CANONICAL_DEVICE_INFO_KEYS)
    assert all(value and value.strip() for value in result.values())


def test_profile_ids_unique() -> None:
    profile_ids = [profile["profile_id"] for profile in CAP_PROFILES.PROFILES]
    assert len(profile_ids) == len(set(profile_ids))


def test_metric_keys_unique_per_profile() -> None:
    for profile in CAP_PROFILES.PROFILES:
        modbus_keys = [
            reg["key"] for reg in profile.get("modbus", {}).get("registers", [])
        ]
        snmp_keys = list(profile.get("snmp", {}).get("oids", {}).keys())
        assert len(modbus_keys) == len(set(modbus_keys))
        assert len(snmp_keys) == len(set(snmp_keys))


def test_snmp_block_metrics_reference_existing_oids() -> None:
    for profile in CAP_PROFILES.PROFILES:
        oids = profile.get("snmp", {}).get("oids", {})
        snmp_blocks = profile.get("snmp", {}).get("snmp_blocks", [])
        for block in snmp_blocks:
            for metric in block.get("metrics", []):
                assert metric in oids


def test_poll_group_values_exist() -> None:
    for profile in CAP_PROFILES.PROFILES:
        poll_groups = profile.get("poll_groups", {})
        assert "slow" in poll_groups

        for reg in profile.get("modbus", {}).get("registers", []):
            group = reg.get("poll_group", "slow")
            assert group in poll_groups
        for block in profile.get("modbus", {}).get("register_blocks", []):
            group = block.get("poll_group", "slow")
            assert group in poll_groups
        for oid_meta in profile.get("snmp", {}).get("oids", {}).values():
            group = oid_meta.get("poll_group", "slow")
            assert group in poll_groups
        for block in profile.get("snmp", {}).get("snmp_blocks", []):
            group = block.get("poll_group", "slow")
            assert group in poll_groups


def test_hybrid_cross_protocol_collisions_require_precedence() -> None:
    for profile in CAP_PROFILES.PROFILES:
        if profile.get("protocol") != "hybrid":
            continue
        modbus_keys = {
            reg["key"] for reg in profile.get("modbus", {}).get("registers", [])
        }
        snmp_keys = set(profile.get("snmp", {}).get("oids", {}).keys())
        overlaps = modbus_keys & snmp_keys
        precedence_keys = set(profile.get("key_precedence", {}).keys())
        assert overlaps.issubset(precedence_keys)
