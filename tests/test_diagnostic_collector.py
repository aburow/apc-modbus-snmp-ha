import importlib.util
import json
import sys
import types
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

if "custom_components.apc_modbus.snmp_helper" not in sys.modules:
    snmp_helper = types.ModuleType("custom_components.apc_modbus.snmp_helper")

    async def async_get_snmp_value(*args, **kwargs):
        return None

    def detect_external_probe_oids_sync(*args, **kwargs):
        del args, kwargs
        return {}

    def get_external_probe_data_detected_sync(*args, **kwargs):
        del args, kwargs
        return {}

    snmp_helper.async_get_snmp_value = async_get_snmp_value
    snmp_helper.detect_external_probe_oids_sync = detect_external_probe_oids_sync
    snmp_helper.get_external_probe_data_detected_sync = (
        get_external_probe_data_detected_sync
    )
    sys.modules["custom_components.apc_modbus.snmp_helper"] = snmp_helper

_load_module(
    "custom_components.apc_modbus.device_types",
    PACKAGE_ROOT / "device_types.py",
)
DIAGNOSTIC_COLLECTOR = _load_module(
    "custom_components.apc_modbus.diagnostic_collector",
    PACKAGE_ROOT / "diagnostic_collector.py",
)


def test_integration_version_matches_manifest() -> None:
    manifest = json.loads((PACKAGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert DIAGNOSTIC_COLLECTOR.INTEGRATION_VERSION == manifest["version"]


def test_detection_summary_uses_exact_runtime_legacy_probe_count() -> None:
    summary = DIAGNOSTIC_COLLECTOR._build_detection_summary(
        {
            "rack_pdu_capabilities": {
                "parsed": {"error": {"code": "modbus_exception"}}
            },
            "rack_pdu_measurements": {
                "parsed": {"error": {"code": "modbus_exception"}}
            },
            "legacy_ups_id": {"parsed": {"registers": [0]}},
            "smt_status": {"parsed": {"registers": [0] * 23}},
            "smt_measurements": {"parsed": {"error": {"code": "modbus_exception"}}},
        }
    )

    assert summary["probe_results"]["legacy_probe_ok"] is True
    assert summary["detected_device_type"] == "smart_ups"


def test_detection_summary_prefers_smt_from_exact_probe_signature() -> None:
    summary = DIAGNOSTIC_COLLECTOR._build_detection_summary(
        {
            "rack_pdu_capabilities": {
                "parsed": {"error": {"code": "modbus_exception"}}
            },
            "rack_pdu_measurements": {
                "parsed": {"error": {"code": "modbus_exception"}}
            },
            "legacy_ups_id": {"parsed": {"error": {"code": "modbus_exception"}}},
            "smt_status": {"parsed": {"registers": [0] * 23}},
            "smt_measurements": {"parsed": {"registers": [0] * 26}},
        }
    )

    assert summary["probe_results"]["smt_measurements_ok"] is True
    assert summary["detected_device_type"] == "smt_ups"


def test_quick_decode_exposes_input_frequency_alias() -> None:
    registers = [0] * 26
    # 6400 / 128 = 50.0 Hz at 0x0090 (offset 16)
    registers[16] = 6400

    quick = DIAGNOSTIC_COLLECTOR._build_quick_decode(registers)

    assert quick["out_freq"] == 50.0
    assert quick["in_freq"] == 50.0


def test_snmp_oids_include_input_frequency_candidates() -> None:
    assert (
        DIAGNOSTIC_COLLECTOR.SNMP_OIDS["apc_input_frequency"]
        == "1.3.6.1.4.1.318.1.1.1.3.2.4.0"
    )
    assert (
        DIAGNOSTIC_COLLECTOR.SNMP_OIDS["upsmib_input_frequency_line1"]
        == "1.3.6.1.2.1.33.1.3.3.1.2.1"
    )


def test_decode_snmp_input_frequency_prefers_apc_oid() -> None:
    decoded = DIAGNOSTIC_COLLECTOR._decode_snmp_input_frequency(
        {
            "apc_input_frequency": {"value": "500"},
            "upsmib_input_frequency_line1": {"value": "49.9"},
        }
    )
    assert decoded == {
        "input_frequency_hz": 50.0,
        "input_frequency_source": "apc_input_frequency",
    }


def test_decode_snmp_input_frequency_uses_upsmib_when_apc_missing() -> None:
    decoded = DIAGNOSTIC_COLLECTOR._decode_snmp_input_frequency(
        {
            "apc_input_frequency": {"error": {"code": "snmp_missing"}},
            "upsmib_input_frequency_line1": {"value": "501"},
        }
    )
    assert decoded == {
        "input_frequency_hz": 50.1,
        "input_frequency_source": "upsmib_input_frequency_line1",
    }


def test_collect_snmp_data_uses_configured_snmp_port() -> None:
    original_get = DIAGNOSTIC_COLLECTOR.async_get_snmp_value
    seen_ports: set[int] = set()

    async def _fake_get(host, oid, community, timeout=5, snmp_port=161):
        del host, oid, community, timeout
        seen_ports.add(snmp_port)
        return None

    DIAGNOSTIC_COLLECTOR.async_get_snmp_value = _fake_get
    try:
        _ = DIAGNOSTIC_COLLECTOR.asyncio.run(
            DIAGNOSTIC_COLLECTOR._collect_snmp_data("192.0.2.1", "public", 1161)
        )
    finally:
        DIAGNOSTIC_COLLECTOR.async_get_snmp_value = original_get

    assert seen_ports == {1161}


def test_modbus_tcp_idle_probe_uses_supplied_timer() -> None:
    sleeps: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    original_sleep = DIAGNOSTIC_COLLECTOR.time.sleep
    original_connect = DIAGNOSTIC_COLLECTOR.socket.create_connection
    original_read = DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection
    original_parse = DIAGNOSTIC_COLLECTOR._parse_modbus_response

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def _fake_connect(*args, **kwargs):
        del args, kwargs
        return _FakeConnection()

    def _fake_read(*args, **kwargs):
        del args, kwargs
        return b"raw"

    def _fake_parse(raw):
        assert raw == b"raw"
        return {"registers": [0]}

    DIAGNOSTIC_COLLECTOR.time.sleep = _fake_sleep
    DIAGNOSTIC_COLLECTOR.socket.create_connection = _fake_connect
    DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection = _fake_read
    DIAGNOSTIC_COLLECTOR._parse_modbus_response = _fake_parse
    try:
        result = DIAGNOSTIC_COLLECTOR._build_modbus_tcp_idle_probe(
            "192.0.2.1",
            502,
            1,
            10,
            keep_connection_open=True,
        )
    finally:
        DIAGNOSTIC_COLLECTOR.time.sleep = original_sleep
        DIAGNOSTIC_COLLECTOR.socket.create_connection = original_connect
        DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection = (
            original_read
        )
        DIAGNOSTIC_COLLECTOR._parse_modbus_response = original_parse

    assert sleeps == [3.0, 10.0]
    assert result["short_idle_seconds_tested"] == 3
    assert result["configured_idle_seconds_tested"] == 10
    assert result["keep_connection_open"] is True
    assert result["short_idle"]["first_read"] == {"ok": True}
    assert result["short_idle"]["second_read"] == {"ok": True}
    assert result["short_idle"]["socket_survived_idle"] is True
    assert result["configured_idle"]["first_read"] == {"ok": True}
    assert result["configured_idle"]["second_read"] == {"ok": True}
    assert result["configured_idle"]["socket_survived_idle"] is True


def test_modbus_tcp_idle_probe_reports_reuse_failure_risk() -> None:
    original_sleep = DIAGNOSTIC_COLLECTOR.time.sleep
    original_connect = DIAGNOSTIC_COLLECTOR.socket.create_connection
    original_read = DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    calls = 0

    def _fake_connect(*args, **kwargs):
        del args, kwargs
        return _FakeConnection()

    def _fake_read(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls == 4:
            raise BrokenPipeError("broken pipe")
        return b"\x00\x01\x00\x00\x00\x05\x01\x03\x02\x00\x00"

    DIAGNOSTIC_COLLECTOR.time.sleep = lambda _seconds: None
    DIAGNOSTIC_COLLECTOR.socket.create_connection = _fake_connect
    DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection = _fake_read
    try:
        result = DIAGNOSTIC_COLLECTOR._build_modbus_tcp_idle_probe(
            "192.0.2.1",
            502,
            1,
            10,
            keep_connection_open=True,
        )
    finally:
        DIAGNOSTIC_COLLECTOR.time.sleep = original_sleep
        DIAGNOSTIC_COLLECTOR.socket.create_connection = original_connect
        DIAGNOSTIC_COLLECTOR._modbus_read_holding_registers_on_connection = (
            original_read
        )

    assert result["short_idle"]["socket_survived_idle"] is True
    assert result["configured_idle"]["socket_survived_idle"] is False
    assert (
        result["configured_idle"]["second_read"]["error"]["exception_type"]
        == "BrokenPipeError"
    )
    assert "Modbus TCP Timeout" in result["risk"]
    assert "configured Home Assistant polling interval" in result["risk"]
    assert "higher than the configured polling interval" in result["risk"]
    assert "disable Keep Connection Open" in result["risk"]


def test_collect_external_probe_tests_success() -> None:
    original_detect = DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync
    original_read = DIAGNOSTIC_COLLECTOR.get_external_probe_data_detected_sync

    detection = {
        "temp_1_oid": "1.3.6.1.4.1.318.1.1.25.1.2.1.6.1.1",
        "humidity_1_oid": None,
        "temp_2_oid": None,
        "humidity_2_oid": None,
        "frequency_oid": "1.3.6.1.4.1.318.1.1.1.3.2.4.0",
    }
    values = {
        "snmp_external_temp_1": 24.5,
        "snmp_input_frequency": 50.0,
    }

    DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync = lambda *_args, **_kwargs: (
        detection
    )
    DIAGNOSTIC_COLLECTOR.get_external_probe_data_detected_sync = (
        lambda *_args, **_kwargs: values
    )
    try:
        result = DIAGNOSTIC_COLLECTOR._collect_external_probe_tests(
            "192.0.2.1", "public", 1161
        )
    finally:
        DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync = original_detect
        DIAGNOSTIC_COLLECTOR.get_external_probe_data_detected_sync = original_read

    assert result["detect"] == {"ok": True, "detection": detection}
    assert result["read_detected"]["ok"] is True
    assert result["read_detected"]["value_count"] == 2
    assert result["read_detected"]["values"] == values


def test_collect_external_probe_tests_detection_failure() -> None:
    original_detect = DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync
    DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync = lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(TimeoutError("snmp timeout"))
    try:
        result = DIAGNOSTIC_COLLECTOR._collect_external_probe_tests(
            "192.0.2.1", "public", 1161
        )
    finally:
        DIAGNOSTIC_COLLECTOR.detect_external_probe_oids_sync = original_detect

    assert result["detect"]["ok"] is False
    assert result["detect"]["error"]["code"] == "snmp_external_probe_detection_failed"
    assert result["detect"]["error"]["exception_type"] == "TimeoutError"
    assert "read_detected" not in result
