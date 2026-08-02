import importlib.util
import struct
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "custom_components" / "apc_modbus"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(ROOT / "custom_components")]
sys.modules.setdefault("custom_components", custom_components)
package = types.ModuleType("custom_components.apc_modbus")
package.__path__ = [str(PACKAGE_ROOT)]
sys.modules.setdefault("custom_components.apc_modbus", package)
snmp = types.ModuleType("custom_components.apc_modbus.snmp_helper")
snmp.async_get_snmp_value = lambda *args, **kwargs: None
snmp.detect_external_probe_oids_sync = lambda *args, **kwargs: {}
snmp.get_external_probe_data_detected_sync = lambda *args, **kwargs: {}
sys.modules.setdefault("custom_components.apc_modbus.snmp_helper", snmp)
load("custom_components.apc_modbus.device_types", PACKAGE_ROOT / "device_types.py")
collector = load(
    "custom_components.apc_modbus.diagnostic_collector",
    PACKAGE_ROOT / "diagnostic_collector.py",
)


def exception(code: int = 2):
    return {"parsed": {"error": {"code": "modbus_exception", "exception_code": code}}}


def response(values: list[int]):
    return {"parsed": {"registers": values}}


def test_diagnostics_share_smt_classifier() -> None:
    summary = collector._build_detection_summary(
        {
            "rack_pdu_capabilities": exception(),
            "rack_pdu_measurements": exception(),
            "legacy_ups_id": exception(),
            "smt_status": response([0] * 23),
            "smt_measurements": response([0] * 26),
        }
    )
    assert summary["detected_device_type"] == "smt_ups"
    assert summary["probe_results"]["legacy_ups_id"]["category"] == "modbus_exception"


def test_diagnostics_keep_transport_failure_ambiguous() -> None:
    summary = collector._build_detection_summary(
        {
            "rack_pdu_capabilities": exception(),
            "rack_pdu_measurements": exception(),
            "legacy_ups_id": {"error": {"code": "connection_refused"}},
            "smt_status": response([0] * 23),
            "smt_measurements": response([0] * 26),
        }
    )
    assert summary["detected_device_type"] is None
    assert summary["decision"] == "ambiguous"


def test_probe_set_has_only_schema_reads() -> None:
    assert collector.MODBUS_PROBES == [
        ("rack_pdu_capabilities", 0x009E, 5),
        ("rack_pdu_measurements", 0x00CF, 6),
        ("legacy_ups_id", 0x0021, 1),
        ("smt_status", 0x0000, 23),
        ("smt_measurements", 0x0080, 26),
    ]


def test_constrained_diagnostics_skip_idle_socket_probe() -> None:
    result = collector._build_modbus_tcp_idle_probe(
        "127.0.0.1",
        502,
        1,
        10,
        transport_mode="one_request_per_connection",
    )
    assert result["skipped_reason"] == "one_request_per_connection"


def test_unavailable_snmp_diagnostics_do_not_call_snmp(monkeypatch) -> None:
    monkeypatch.setattr(
        collector,
        "_collect_snmp_data",
        lambda *args: (_ for _ in ()).throw(AssertionError("SNMP called")),
    )
    monkeypatch.setattr(
        collector,
        "_collect_external_probe_tests",
        lambda *args: (_ for _ in ()).throw(AssertionError("SNMP called")),
    )
    monkeypatch.setattr(
        collector, "_collect_modbus_block", lambda *args: {"parsed": {}}
    )
    monkeypatch.setattr(
        collector, "_build_modbus_tcp_idle_probe", lambda *args, **kwargs: {}
    )
    dump = collector.collect_diagnostic_dump(
        "127.0.0.1", "public", 502, 1, snmp_availability="unavailable"
    )
    assert dump["snmp"] == {"skipped_reason": "snmp_unavailable"}
    assert dump["external_probe_tests"] == {"skipped_reason": "snmp_unavailable"}


def test_constrained_diagnostics_pace_every_fresh_connection(monkeypatch) -> None:
    pauses = []
    monkeypatch.setattr(collector.time, "sleep", pauses.append)
    monkeypatch.setattr(
        collector, "_collect_modbus_block", lambda *args: {"parsed": {}}
    )
    monkeypatch.setattr(
        collector, "_build_modbus_tcp_idle_probe", lambda *args, **kwargs: {}
    )
    dump = collector.collect_diagnostic_dump(
        "127.0.0.1",
        "public",
        502,
        1,
        transport_mode="one_request_per_connection",
        transport_promotion_reason="ConnectionRefusedError",
        snmp_availability="unavailable",
    )
    request_count = len(collector.MODBUS_BLOCKS) + sum(
        (start, count) not in collector.MODBUS_BLOCKS
        for _name, start, count in collector.MODBUS_PROBES
    )
    assert pauses == [collector.ONE_REQUEST_INTER_REQUEST_DELAY_SECONDS] * (
        request_count - 1
    )
    assert dump["transport"]["promotion_reason"] == "ConnectionRefusedError"


def test_modbus_read_handles_fragmented_tcp_responses() -> None:
    header = struct.pack(">HHHB", 1, 0, 5, 1)
    socket_chunks = [header[:3], header[3:], b"\x03", b"\x02\x12\x34"]

    class FragmentedSocket:
        def sendall(self, _payload: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return socket_chunks.pop(0)

    assert (
        collector._modbus_read_holding_registers_on_connection(
            FragmentedSocket(), 1, 0, 1
        )
        == header + b"\x03\x02\x12\x34"
    )
