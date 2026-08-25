"""Read-only 2.1 regression contracts for HA-dependent coordinator paths."""

import asyncio
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/apc_modbus"
COORDINATOR = (COMPONENT / "coordinator.py").read_text()


def _extract_method(name: str, *, async_def: bool = False) -> str:
    marker = f"    {'async ' if async_def else ''}def {name}("
    start = COORDINATOR.index(marker)
    rest = COORDINATOR[start + 1 :]
    end = min(
        index for index in (rest.find("\n    def "), rest.find("\n    @")) if index >= 0
    )
    return textwrap.dedent(COORDINATOR[start : start + 1 + end])


def test_runtime_has_only_the_v2_transport_command_seam() -> None:
    runtime = "\n".join(path.read_text() for path in COMPONENT.glob("*.py"))

    assert not (COMPONENT / "write_support.py").exists()
    assert "async_execute_write" not in runtime
    assert "write_operation_available" not in runtime
    assert "modbus_commands" in runtime
    assert "async with self.io_lock:" in (COMPONENT / "modbus_transport.py").read_text()


def test_one_modbus_outage_warning_is_followed_by_one_recovery_message() -> None:
    namespace = {"time": __import__("time"), "_LOGGER": Mock()}
    exec(_extract_method("_record_modbus_failure"), namespace)  # noqa: S102
    exec(_extract_method("_record_modbus_recovery"), namespace)  # noqa: S102
    failure = namespace["_record_modbus_failure"]
    recovery = namespace["_record_modbus_recovery"]
    coordinator = SimpleNamespace(
        _modbus_failure_started=None,
        _modbus_failure_warning_emitted=False,
        _log_ctx="UPS 192.0.2.1:502 (unit 1)",
    )

    with patch("time.monotonic", side_effect=(100.0, 112.5)):
        failure(coordinator, "timeout")
        failure(coordinator, "timeout")
        recovery(coordinator)
        recovery(coordinator)

    assert namespace["_LOGGER"].warning.call_count == 1
    assert namespace["_LOGGER"].info.call_count == 1
    assert coordinator._modbus_failure_started is None
    assert not coordinator._modbus_failure_warning_emitted


def test_snmp_capabilities_log_only_when_the_detected_features_change() -> None:
    namespace = {
        "time": __import__("time"),
        "_LOGGER": Mock(),
        "METADATA_REFRESH_INTERVAL_SECONDS": 3600,
        "get_device_metadata_sync": object(),
        "detect_external_probe_oids_sync": object(),
        "has_usable_metadata": lambda metadata: bool(metadata),
    }
    exec(_extract_method("_maybe_refresh_snmp_metadata", async_def=True), namespace)  # noqa: S102
    exec(_extract_method("_snmp_features"), namespace)  # noqa: S102
    refresh = namespace["_maybe_refresh_snmp_metadata"]
    features = namespace["_snmp_features"]

    detection = {"temp_1_oid": "1.2.3", "humidity_1_oid": None}

    async def executor_job(job, *args):
        if job is namespace["get_device_metadata_sync"]:
            return {"model": "SMT750IC"}
        assert job is namespace["detect_external_probe_oids_sync"]
        return detection

    coordinator = SimpleNamespace(
        snmp_availability="available",
        _metadata_needs_refresh=True,
        _metadata_last_refresh_monotonic=0.0,
        _snmp_probe_detection={},
        hass=SimpleNamespace(async_add_executor_job=executor_job),
        host="192.0.2.1",
        snmp_community="public",
        device_type="smt_ups",
        snmp_port=161,
        _log_ctx="UPS 192.0.2.1:502 (unit 1)",
        set_snmp_availability=Mock(),
        set_device_metadata=Mock(),
    )
    coordinator._snmp_features = features

    asyncio.run(refresh(coordinator))
    asyncio.run(refresh(coordinator))

    assert namespace["_LOGGER"].info.call_count == 1
    assert namespace["_LOGGER"].debug.call_count == 1
