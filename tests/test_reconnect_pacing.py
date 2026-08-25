"""Behavioural test for the SmartConnect reconnect-pacing gate.

Exercises the real `_reconnect_pacing_remaining` method (pure time math, no
pymodbus/homeassistant dependency) plus source-level checks that every TCP
connect() site waits on it and every close() site records the close, since
coordinator.py itself can't be imported without homeassistant/pymodbus
installed in this environment (see test_issue15a_transport_contract.py for
the same constraint).
"""

import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


TRANSPORT = (
    Path(__file__).resolve().parents[1]
    / "custom_components/apc_modbus/modbus_transport.py"
).read_text()
COORDINATOR = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/coordinator.py"
).read_text()


def _extract_method(name: str) -> str:
    marker = f"    def {name}("
    start = TRANSPORT.index(marker)
    # Grab this method's body up to the next same-indent def/decorator.
    rest = TRANSPORT[start + 1 :]
    end = rest.index("\n    def ")
    return TRANSPORT[start : start + 1 + end]


def _make_reconnect_pacing_remaining():
    """Bind the real _reconnect_pacing_remaining source onto a fake self."""
    src = textwrap.dedent(_extract_method("reconnect_pacing_remaining"))
    namespace: dict = {"time": __import__("time")}
    exec(src, namespace)  # noqa: S102 - loading real source, not user input
    return namespace["reconnect_pacing_remaining"]


def test_no_delay_when_device_has_no_minimum_gap_configured() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(min_reconnect_delay=0.0, last_close_monotonic=100.0)
    assert fn(fake_self) == 0.0


def test_no_delay_when_connection_has_never_been_closed() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(min_reconnect_delay=2.0, last_close_monotonic=0.0)
    assert fn(fake_self) == 0.0


def test_waits_out_the_remaining_gap_after_a_recent_close() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(min_reconnect_delay=2.0, last_close_monotonic=100.0)
    with patch("time.monotonic", return_value=100.7):
        assert fn(fake_self) == pytest.approx(2.0 - 0.7)


def test_no_wait_once_the_gap_has_already_elapsed() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(min_reconnect_delay=2.0, last_close_monotonic=100.0)
    with patch("time.monotonic", return_value=103.0):
        assert fn(fake_self) == 0.0


def test_smartconnect_configures_a_two_second_minimum_gap() -> None:
    assert "self._min_reconnect_delay = 2.0" in COORDINATOR
    branch = COORDINATOR.split(
        "elif self.device_type == APCDeviceType.SMARTCONNECT_UPS:", 1
    )[1][:200]
    assert "self._min_reconnect_delay = 2.0" in branch


def test_every_tcp_connect_site_waits_on_reconnect_pacing() -> None:
    # Persistent-session connect/reconnect (idle-timeout and error recovery).
    assert TRANSPORT.count("await self._await_reconnect_pacing()") >= 2
    assert "self.client.connect" in TRANSPORT
    # One-request-per-connection mode (runs in an executor thread).
    assert "remaining = self.reconnect_pacing_remaining()" in TRANSPORT
    assert "time.sleep(remaining)" in TRANSPORT


def test_every_tcp_close_site_records_the_close_time() -> None:
    assert TRANSPORT.count("self._mark_closed()") >= 2
    assert "finally:\n            self._mark_closed()" in TRANSPORT
