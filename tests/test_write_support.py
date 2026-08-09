"""Behavioral tests for pure Modbus write safety rules."""

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys

import pytest

path = (
    Path(__file__).resolve().parents[1]
    / "custom_components/apc_modbus/write_support.py"
)
spec = importlib.util.spec_from_file_location("apc_write_support", path)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

AlarmStatus = module.AlarmStatus
OutletAction = module.OutletAction
OutletTarget = module.OutletTarget
build_outlet_command = module.build_outlet_command
decode_alarm_status = module.decode_alarm_status
decode_battery_test_status = module.decode_battery_test_status
decode_operation_status = module.decode_operation_status
decode_outlet_status = module.decode_outlet_status
decode_runtime_calibration_status = module.decode_runtime_calibration_status
encode_int32 = module.encode_int32
outlet_precondition = module.outlet_precondition
parse_firmware = module.parse_firmware
protocol_constants_valid = module.protocol_constants_valid
release_sku_supported = module.release_sku_supported
validate_write_multiple_response = module.validate_write_multiple_response
validate_write_single_response = module.validate_write_single_response
vendor_family_eligible = module.vendor_family_eligible


@dataclass
class Response:
    address: int
    registers: list[int] | None = None
    value: int | None = None
    count: int | None = None
    retries: int = 0
    error: bool = False

    def isError(self) -> bool:
        return self.error


def test_sku_and_protocol_gates_are_exact() -> None:
    assert parse_firmware("UPS 10.2 (ID20)") == (10, 2)
    assert vendor_family_eligible("SMT1500", "UPS 9.0")
    assert not vendor_family_eligible("SMT1500", "UPS 8.9")
    assert not vendor_family_eligible("SMT750RM1U", "UPS 15.0")
    assert vendor_family_eligible("SMX1500", "10.0")
    assert not vendor_family_eligible("SMX1500", "9.9")
    assert not vendor_family_eligible("SRT3000", "1.0")
    assert not vendor_family_eligible("SRC3KUXIX709", "1.0")
    assert not vendor_family_eligible("SRC3KUX", "99.0")
    assert not vendor_family_eligible("SURTD5000", "99.0")
    accepted = {("SMT1500", (9, 0))}
    assert release_sku_supported("SMT1500", "UPS 9.0", accepted)
    assert not release_sku_supported("SMT1500", "UPS 9.1", accepted)
    assert not release_sku_supported("SMT", "UPS 9.0", accepted)
    assert release_sku_supported("SMT750ic", "UPS 18.0")
    assert not release_sku_supported("SMT750IC", "UPS 18.1")
    constants = {
        0x0802: (0x3132, 0x3334, 0x3536, 0x3738),
        0x0806: (0x1234, 0x5678),
        0x080A: (0x1234,),
    }
    assert protocol_constants_valid(constants)
    constants[0x080A] = (0x1235,)
    assert not protocol_constants_valid(constants)


def test_command_vectors_and_signed_word_order() -> None:
    assert build_outlet_command(OutletAction.ON, OutletTarget.MOG) == (2, 0x0102)
    assert build_outlet_command(OutletAction.OFF, OutletTarget.MOG) == (2, 0x0104)
    assert build_outlet_command(OutletAction.ON, OutletTarget.SOG_0) == (2, 0x0202)
    assert build_outlet_command(OutletAction.ON, OutletTarget.SOG_1) == (2, 0x0402)
    assert build_outlet_command(OutletAction.ON, OutletTarget.SOG_2) == (2, 0x0802)
    for action, low_action in (
        (OutletAction.CANCEL, 0x0001),
        (OutletAction.ON, 0x0002),
        (OutletAction.OFF, 0x0004),
        (OutletAction.SHUTDOWN, 0x0008),
        (OutletAction.REBOOT, 0x0010),
    ):
        for target, low_target in (
            (OutletTarget.MOG, 0x0100),
            (OutletTarget.SOG_0, 0x0200),
            (OutletTarget.SOG_1, 0x0400),
            (OutletTarget.SOG_2, 0x0800),
        ):
            assert build_outlet_command(action, target) == (
                0x0002,
                low_action | low_target,
            )
    assert encode_int32(-5) == (0xFFFF, 0xFFFB)
    with pytest.raises(ValueError):
        encode_int32(2**31)


def test_status_decoding_and_preconditions() -> None:
    on = decode_outlet_status(1)
    off = decode_outlet_status(2)
    pending = decode_outlet_status(1 | (1 << 3))
    assert on.valid and on.is_on and not on.pending
    assert off.valid and off.is_off
    assert pending.valid and pending.pending and pending.process == "shutdown"
    assert not decode_outlet_status(3).valid
    assert not decode_outlet_status(1 << 15).valid
    statuses = {OutletTarget.MOG: off, OutletTarget.SOG_0: off}
    assert (
        outlet_precondition(OutletAction.ON, OutletTarget.SOG_0, statuses)
        == "outlet_mog_must_be_on"
    )
    statuses[OutletTarget.MOG] = on
    assert outlet_precondition(OutletAction.ON, OutletTarget.SOG_0, statuses) is None
    statuses[OutletTarget.SOG_0] = on
    assert (
        outlet_precondition(OutletAction.OFF, OutletTarget.MOG, statuses)
        == "outlet_sog_must_be_off"
    )
    assert (
        outlet_precondition(OutletAction.CANCEL, OutletTarget.MOG, statuses)
        == "outlet_nothing_to_cancel"
    )
    statuses[OutletTarget.MOG] = pending
    assert outlet_precondition(OutletAction.CANCEL, OutletTarget.MOG, statuses) is None

    for bit, state in enumerate(
        ("pending", "in_progress", "passed", "failed", "refused", "aborted")
    ):
        decoded = decode_operation_status(1 << bit)
        assert decoded.state == state
        assert decoded.active is (bit < 2)
    assert not decode_operation_status(1 << 12).valid
    assert not decode_battery_test_status((1 << 4) | (1 << 12)).valid
    refused_with_overcharge = decode_runtime_calibration_status((1 << 4) | (1 << 15))
    aborted_with_load_change = decode_runtime_calibration_status((1 << 5) | (1 << 12))
    assert refused_with_overcharge.valid and refused_with_overcharge.state == "refused"
    assert (
        aborted_with_load_change.valid and aborted_with_load_change.state == "aborted"
    )
    assert not decode_runtime_calibration_status(0xFFFF).valid
    assert decode_alarm_status(2) == AlarmStatus(2, True, False, True)
    assert decode_alarm_status(4) == AlarmStatus(4, False, True, True)


def test_write_response_validation_is_exact_and_zero_retry() -> None:
    assert validate_write_single_response(Response(0x0605, [1]), 0x0605, 1)
    assert validate_write_single_response(Response(0x0605, value=1), 0x0605, 1)
    assert not validate_write_single_response(Response(0x0605, [2]), 0x0605, 1)
    assert not validate_write_single_response(
        Response(0x0605, [1], retries=1), 0x0605, 1
    )
    assert not validate_write_single_response(
        Response(0x0605, [1], error=True), 0x0605, 1
    )
    assert validate_write_multiple_response(Response(0x0602, count=2), 0x0602, 2)
    assert not validate_write_multiple_response(Response(0x0602, count=1), 0x0602, 2)
