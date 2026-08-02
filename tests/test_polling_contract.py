"""Regression contracts for coordinator polling behaviour."""

from pathlib import Path


COORDINATOR = (
    Path(__file__).resolve().parents[1] / "custom_components/apc_modbus/coordinator.py"
).read_text()


def test_partial_block_reads_use_the_individual_read_fallback() -> None:
    assert (
        "return block_success_count == len(self.register_blocks) and not errors"
        in COORDINATOR
    )


def test_self_test_snmp_polling_is_throttled() -> None:
    assert "SELF_TEST_REFRESH_INTERVAL_SECONDS = 60" in COORDINATOR
    assert "data.update(self._snmp_self_test_data)" in COORDINATOR


def test_modbus_session_lifecycle_is_serialized_and_quiet() -> None:
    assert "async with self._io_lock:" in COORDINATOR
    assert "same_endpoint_entries == 1" in COORDINATOR
    assert '_LOGGER.info(\n            "[%s] Starting update cycle' not in COORDINATOR
