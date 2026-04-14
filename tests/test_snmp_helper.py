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
