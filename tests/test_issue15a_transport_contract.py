"""Focused source-level regression checks for HA-dependent Issue 15a paths."""

from pathlib import Path


COORDINATOR = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/coordinator.py"
).read_text()
INIT = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/__init__.py"
).read_text()
TRANSPORT = (
    Path(__file__).resolve().parents[1]
    / "custom_components/apc_modbus/modbus_transport.py"
).read_text()


def test_transport_promotion_retries_without_stale_session_data() -> None:
    assert "def _promote_transport_mode" in COORDINATOR
    assert "data.clear()" in COORDINATOR
    assert "def _read_one_request" in TRANSPORT
    assert "self.client.close()" in TRANSPORT
    assert "CONF_TRANSPORT_MODE" in INIT
    assert "transport_mode_persist=" in INIT


def test_unavailable_snmp_gates_all_routine_helpers() -> None:
    assert COORDINATOR.count('self.snmp_availability != "available"') >= 2
    assert 'self.snmp_availability == "unavailable"' in COORDINATOR
    assert "def set_snmp_availability" in COORDINATOR
