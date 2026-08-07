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


COORDINATOR = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/coordinator.py"
).read_text()


def _extract_method(name: str) -> str:
    marker = f"    def {name}("
    start = COORDINATOR.index(marker)
    # Grab this method's body up to the next same-indent def/decorator.
    rest = COORDINATOR[start + 1 :]
    end = rest.index("\n    def ")
    return COORDINATOR[start : start + 1 + end]


def _make_reconnect_pacing_remaining():
    """Bind the real _reconnect_pacing_remaining source onto a fake self."""
    src = textwrap.dedent(_extract_method("_reconnect_pacing_remaining"))
    namespace: dict = {"time": __import__("time")}
    exec(src, namespace)  # noqa: S102 - loading real source, not user input
    return namespace["_reconnect_pacing_remaining"]


def test_no_delay_when_device_has_no_minimum_gap_configured() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(_min_reconnect_delay=0.0, _last_close_monotonic=100.0)
    assert fn(fake_self) == 0.0


def test_no_delay_when_connection_has_never_been_closed() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(_min_reconnect_delay=2.0, _last_close_monotonic=0.0)
    assert fn(fake_self) == 0.0


def test_waits_out_the_remaining_gap_after_a_recent_close() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(_min_reconnect_delay=2.0, _last_close_monotonic=100.0)
    with patch("time.monotonic", return_value=100.7):
        assert fn(fake_self) == pytest.approx(2.0 - 0.7)


def test_no_wait_once_the_gap_has_already_elapsed() -> None:
    fn = _make_reconnect_pacing_remaining()
    fake_self = SimpleNamespace(_min_reconnect_delay=2.0, _last_close_monotonic=100.0)
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
    assert (
        "await self._await_reconnect_pacing()\n"
        "            connect_start = time.monotonic()\n"
        "            connect_request = functools.partial(self.client.connect)"
    ) in COORDINATOR
    assert (
        "await self._await_reconnect_pacing()\n"
        "        reconnect_start = time.monotonic()\n"
        "        connect_request = functools.partial(self.client.connect)"
    ) in COORDINATOR
    # One-request-per-connection mode (runs in an executor thread).
    assert "remaining = self._reconnect_pacing_remaining()" in COORDINATOR
    assert COORDINATOR.count("remaining = self._reconnect_pacing_remaining()") >= 1
    assert "time.sleep(remaining)" in COORDINATOR


def test_every_tcp_close_site_records_the_close_time() -> None:
    assert COORDINATOR.count("self._mark_closed()") >= 3
    keep_open_toggle = COORDINATOR.split("async def async_set_keep_connection_open", 1)[
        1
    ].split("def mark_snmp_metadata_refresh_needed", 1)[0]
    assert "finally:\n                    self._mark_closed()" in keep_open_toggle
