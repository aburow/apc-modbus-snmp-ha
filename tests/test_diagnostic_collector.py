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
