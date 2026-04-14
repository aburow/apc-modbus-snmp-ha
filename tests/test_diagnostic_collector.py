import importlib.util
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

    snmp_helper.async_get_snmp_value = async_get_snmp_value
    sys.modules["custom_components.apc_modbus.snmp_helper"] = snmp_helper

_load_module(
    "custom_components.apc_modbus.device_types",
    PACKAGE_ROOT / "device_types.py",
)
DIAGNOSTIC_COLLECTOR = _load_module(
    "custom_components.apc_modbus.diagnostic_collector",
    PACKAGE_ROOT / "diagnostic_collector.py",
)


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
