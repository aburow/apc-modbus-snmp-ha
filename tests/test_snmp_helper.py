import importlib.util
import asyncio
import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "custom_components" / "apc_modbus"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


if "custom_components" not in sys.modules:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components

if "custom_components.apc_modbus" not in sys.modules:
    apc_modbus = types.ModuleType("custom_components.apc_modbus")
    apc_modbus.__path__ = [str(PACKAGE_ROOT)]
    sys.modules["custom_components.apc_modbus"] = apc_modbus

if "pysnmp.hlapi.v3arch.asyncio" not in sys.modules:
    pysnmp = types.ModuleType("pysnmp")
    hlapi = types.ModuleType("pysnmp.hlapi")
    v3arch = types.ModuleType("pysnmp.hlapi.v3arch")
    asyncio_mod = types.ModuleType("pysnmp.hlapi.v3arch.asyncio")

    class _Dummy:
        def __init__(self, *args, **kwargs):
            pass

    async def _dummy_get_cmd(*args, **kwargs):
        return (None, None, None, [])

    asyncio_mod.CommunityData = _Dummy
    asyncio_mod.ContextData = _Dummy
    asyncio_mod.ObjectIdentity = _Dummy
    asyncio_mod.ObjectType = _Dummy
    asyncio_mod.SnmpEngine = _Dummy
    asyncio_mod.UdpTransportTarget = _Dummy
    asyncio_mod.get_cmd = _dummy_get_cmd

    sys.modules["pysnmp"] = pysnmp
    sys.modules["pysnmp.hlapi"] = hlapi
    sys.modules["pysnmp.hlapi.v3arch"] = v3arch
    sys.modules["pysnmp.hlapi.v3arch.asyncio"] = asyncio_mod

_load_module(
    "custom_components.apc_modbus.device_types", PACKAGE_ROOT / "device_types.py"
)
SNMP_HELPER = _load_module(
    "custom_components.apc_modbus.snmp_helper",
    PACKAGE_ROOT / "snmp_helper.py",
)


def test_parse_frequency_hz_handles_hz_and_tenths() -> None:
    assert SNMP_HELPER._parse_frequency_hz("50") == 50.0
    assert SNMP_HELPER._parse_frequency_hz("500") == 50.0
    assert SNMP_HELPER._parse_frequency_hz("600") == 60.0
    assert SNMP_HELPER._parse_frequency_hz("0") is None
    assert SNMP_HELPER._parse_frequency_hz("-1") is None
    assert SNMP_HELPER._parse_frequency_hz("not-a-number") is None


def test_parse_external_probe_values_accept_float_and_suffix_text() -> None:
    assert SNMP_HELPER._parse_external_temp_c("25.0") == 25.0
    assert SNMP_HELPER._parse_external_temp_c("25 C") == 25.0
    assert SNMP_HELPER._parse_external_temp_c("250") == 25.0
    assert SNMP_HELPER._parse_external_humidity_pct("45.0") == 45.0
    assert SNMP_HELPER._parse_external_humidity_pct("45 %") == 45.0
    assert SNMP_HELPER._parse_external_humidity_pct("450") == 45.0


def test_self_test_data_uses_only_the_five_read_only_oids_and_decodes_values() -> None:
    calls: list[str] = []
    values = {
        SNMP_HELPER.SELF_TEST_OIDS["snmp_self_test_schedule"]: "3",
        SNMP_HELPER.SELF_TEST_OIDS["snmp_self_test_result"]: "1",
        SNMP_HELPER.SELF_TEST_OIDS["snmp_last_self_test_date"]: "07/31/26",
        SNMP_HELPER.SELF_TEST_OIDS["snmp_self_test_time"]: "09:30",
    }

    async def _fake_get(*args, **kwargs):
        calls.append(args[1])
        return values.get(args[1])

    original = SNMP_HELPER.async_get_snmp_value
    SNMP_HELPER.async_get_snmp_value = _fake_get
    try:
        parsed = asyncio.run(SNMP_HELPER.async_get_self_test_data("127.0.0.1"))
    finally:
        SNMP_HELPER.async_get_snmp_value = original

    assert set(calls) == set(SNMP_HELPER.SELF_TEST_OIDS.values())
    assert "1.3.6.1.4.1.318.1.1.1.7.2.2.0" not in SNMP_HELPER.SELF_TEST_OIDS.values()
    assert parsed == {
        "snmp_self_test_schedule": 3,
        "snmp_self_test_result": 1,
        "snmp_last_self_test_date": date(2026, 7, 31),
        "snmp_self_test_time": "09:30",
        "snmp_self_test_day": None,
    }


def test_self_test_parsers_reject_invalid_dates_and_times() -> None:
    assert SNMP_HELPER._parse_self_test_date("07/31/26") == date(2026, 7, 31)
    assert SNMP_HELPER._parse_self_test_date("07/31/2026") == date(2026, 7, 31)
    assert SNMP_HELPER._parse_self_test_date("13/31/26") is None
    assert SNMP_HELPER._parse_self_test_time("24:00") is None
    assert SNMP_HELPER._parse_self_test_time("9:30") is None


def test_dedupe_oids_preserves_order() -> None:
    assert SNMP_HELPER._dedupe_oids_preserve_order(["1", "2", "1", "3", "2"]) == [
        "1",
        "2",
        "3",
    ]


def test_select_first_usable_candidate_is_local_only() -> None:
    calls: list[str] = []

    async def _should_not_be_called(*_args, **_kwargs):
        calls.append("called")
        return None

    original = SNMP_HELPER.async_get_snmp_value
    SNMP_HELPER.async_get_snmp_value = _should_not_be_called
    try:
        selected = SNMP_HELPER._select_first_usable_candidate_from_map(
            ["oid_primary", "oid_fallback"],
            {"oid_primary": "bad", "oid_fallback": "500"},
            SNMP_HELPER._parse_frequency_hz,
        )
        assert selected == "oid_fallback"
        assert calls == []
    finally:
        SNMP_HELPER.async_get_snmp_value = original


def test_detect_external_probe_oids_dedup_and_order() -> None:
    calls: list[str] = []
    values = {
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_TEMP_C_BASE}.1.1": "100",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_TEMP_C_BASE}.1": "101",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_HUMIDITY_BASE}.1.1": "450",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_HUMIDITY_BASE}.1": "46",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_TEMP_C_BASE}.2.1": "200",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_TEMP_C_BASE}.2": "201",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_HUMIDITY_BASE}.2.1": "550",
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_HUMIDITY_BASE}.2": "56",
        SNMP_HELPER.SMARTUPS_OID_INPUT_FREQUENCY: "bad",
        SNMP_HELPER.UPS_MIB_OID_INPUT_FREQUENCY_LINE1: "500",
    }

    async def _fake_get(
        host: str,
        oid: str,
        community: str = "public",
        timeout: int = 5,
        snmp_port: int = 161,
    ):
        del host, community, timeout, snmp_port
        calls.append(oid)
        return values.get(oid)

    original = SNMP_HELPER.async_get_snmp_value
    SNMP_HELPER.async_get_snmp_value = _fake_get
    try:
        detection = asyncio.run(
            SNMP_HELPER.async_detect_external_probe_oids("127.0.0.1", "public")
        )
    finally:
        SNMP_HELPER.async_get_snmp_value = original

    assert len(calls) == len(set(calls))
    assert detection["frequency_oid"] == SNMP_HELPER.UPS_MIB_OID_INPUT_FREQUENCY_LINE1
    assert detection["temp_1_oid"] == f"{SNMP_HELPER.UIO_SENSOR_STATUS_TEMP_C_BASE}.1.1"
    assert detection["humidity_1_oid"] == (
        f"{SNMP_HELPER.UIO_SENSOR_STATUS_HUMIDITY_BASE}.1.1"
    )


def test_detected_probe_fetch_dedups_duplicate_oids_and_maps_all_keys() -> None:
    calls: list[str] = []
    shared_oid = "1.3.6.1.4.1.318.1.1.25.1.2.1.6.1.1"
    values = {shared_oid: "250"}

    async def _fake_get(
        host: str,
        oid: str,
        community: str = "public",
        timeout: int = 5,
        snmp_port: int = 161,
    ):
        del host, community, timeout, snmp_port
        calls.append(oid)
        return values.get(oid)

    detection = {
        "frequency_oid": None,
        "temp_1_oid": shared_oid,
        "humidity_1_oid": None,
        "temp_2_oid": shared_oid,
        "humidity_2_oid": None,
    }

    original = SNMP_HELPER.async_get_snmp_value
    SNMP_HELPER.async_get_snmp_value = _fake_get
    try:
        parsed = asyncio.run(
            SNMP_HELPER.async_get_external_probe_data_detected(
                "127.0.0.1", "public", detection
            )
        )
    finally:
        SNMP_HELPER.async_get_snmp_value = original

    assert calls == [shared_oid]
    assert parsed["snmp_external_temp_1"] == 25.0
    assert parsed["snmp_external_temp_2"] == 25.0
