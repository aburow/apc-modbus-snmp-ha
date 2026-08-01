import importlib.util
from pathlib import Path


path = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/snmp_state.py"
)
spec = importlib.util.spec_from_file_location("apc_snmp_state", path)
assert spec and spec.loader
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


def test_explicit_retry_only_marks_nonempty_metadata_usable() -> None:
    assert not state.has_usable_metadata(None)
    assert not state.has_usable_metadata({})
    assert not state.has_usable_metadata({"model": None})
    assert state.has_usable_metadata({"model": "Smart-UPS 750"})
