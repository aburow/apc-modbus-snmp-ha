# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure safety rules for the allowlisted APC Modbus write surface."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Collection


class WriteCapability(StrEnum):
    """Independently discovered write features."""

    OUTLET_MOG = "outlet_mog"
    OUTLET_SOG_0 = "outlet_sog_0"
    OUTLET_SOG_1 = "outlet_sog_1"
    OUTLET_SOG_2 = "outlet_sog_2"
    BATTERY_TEST = "battery_test"
    RUNTIME_CALIBRATION = "runtime_calibration"
    AUDIBLE_ALARM = "audible_alarm"
    OUTLET_SETTINGS_MOG = "outlet_settings_mog"
    OUTLET_SETTINGS_SOG_0 = "outlet_settings_sog_0"
    OUTLET_SETTINGS_SOG_1 = "outlet_settings_sog_1"
    OUTLET_SETTINGS_SOG_2 = "outlet_settings_sog_2"


class OutletTarget(StrEnum):
    MOG = "mog"
    SOG_0 = "sog_0"
    SOG_1 = "sog_1"
    SOG_2 = "sog_2"


class OutletAction(StrEnum):
    CANCEL = "cancel"
    ON = "on"
    OFF = "off"
    SHUTDOWN = "shutdown"
    REBOOT = "reboot"


class WriteOperation(StrEnum):
    OUTLET = "outlet"
    BATTERY_TEST_START = "battery_test_start"
    BATTERY_TEST_ABORT = "battery_test_abort"
    CALIBRATION_START = "calibration_start"
    CALIBRATION_ABORT = "calibration_abort"
    ALARM_MUTE = "alarm_mute"
    ALARM_CANCEL_MUTE = "alarm_cancel_mute"


OUTLET_CAPABILITIES = {
    OutletTarget.MOG: WriteCapability.OUTLET_MOG,
    OutletTarget.SOG_0: WriteCapability.OUTLET_SOG_0,
    OutletTarget.SOG_1: WriteCapability.OUTLET_SOG_1,
    OutletTarget.SOG_2: WriteCapability.OUTLET_SOG_2,
}
OUTLET_STATUS_KEYS = {
    OutletTarget.MOG: "outlet_status_mog",
    OutletTarget.SOG_0: "outlet_status_sog_0",
    OutletTarget.SOG_1: "outlet_status_sog_1",
    OutletTarget.SOG_2: "outlet_status_sog_2",
}
OUTLET_STATUS_ADDRESSES = {
    OutletTarget.MOG: 0x0003,
    OutletTarget.SOG_0: 0x0006,
    OutletTarget.SOG_1: 0x0009,
    OutletTarget.SOG_2: 0x000C,
}
OUTLET_TARGET_BITS = {
    OutletTarget.MOG: 8,
    OutletTarget.SOG_0: 9,
    OutletTarget.SOG_1: 10,
    OutletTarget.SOG_2: 11,
}
OUTLET_ACTION_BITS = {
    OutletAction.CANCEL: 0,
    OutletAction.ON: 1,
    OutletAction.OFF: 2,
    OutletAction.SHUTDOWN: 3,
    OutletAction.REBOOT: 4,
}
COMMANDS: dict[WriteOperation, tuple[int, tuple[int, ...]]] = {
    WriteOperation.BATTERY_TEST_START: (0x0605, (0x0001,)),
    WriteOperation.BATTERY_TEST_ABORT: (0x0605, (0x0002,)),
    WriteOperation.CALIBRATION_START: (0x0606, (0x0001,)),
    WriteOperation.CALIBRATION_ABORT: (0x0606, (0x0002,)),
    WriteOperation.ALARM_MUTE: (0x0607, (0x0004,)),
    WriteOperation.ALARM_CANCEL_MUTE: (0x0607, (0x0008,)),
}
COMMAND_ADDRESSES = frozenset({0x0602, 0x0605, 0x0606, 0x0607})
PROTOCOL_TESTS = {
    0x0802: (0x3132, 0x3334, 0x3536, 0x3738),
    0x0806: (0x1234, 0x5678),
    0x080A: (0x1234,),
}
SRC_MODELS = frozenset({"SRC2KUXI", "SRC3KUXI", "SRC3KUXIX709"})

# Development candidate for controlled physical acceptance on a noncritical load.
RELEASE_SUPPORTED_MODELS: frozenset[tuple[str, tuple[int, ...]]] = frozenset(
    {("SMT750IC", (18, 0))}
)

WRITE_ENTITY_SUFFIXES: dict[str, tuple[str, ...]] = {
    **{
        capability.value: (
            f"write_outlet_{target.value}",
            f"write_outlet_{target.value}_shutdown",
            f"write_outlet_{target.value}_reboot",
            f"write_outlet_{target.value}_cancel",
            f"outlet_{target.value}_operation_state",
        )
        for target, capability in OUTLET_CAPABILITIES.items()
    },
    WriteCapability.BATTERY_TEST.value: (
        "write_battery_test_start",
        "write_battery_test_abort",
        "battery_test_operation_state",
    ),
    WriteCapability.RUNTIME_CALIBRATION.value: (
        "write_calibration_start",
        "write_calibration_abort",
        "runtime_calibration_operation_state",
    ),
    WriteCapability.AUDIBLE_ALARM.value: ("write_alarm_mute",),
}


def write_entity_unique_ids(entry_id: str, capabilities: Collection[str]) -> set[str]:
    """Return only the known entity IDs for authorized or unresolved features."""
    return {
        f"apc_modbus_{entry_id}_{suffix}"
        for capability in capabilities
        for suffix in WRITE_ENTITY_SUFFIXES.get(capability, ())
    }


def parse_firmware(value: str | None) -> tuple[int, ...] | None:
    """Extract a numeric firmware version without lexical comparisons."""
    if not value:
        return None
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)+|\d+)(?!\d)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def vendor_family_eligible(model: str | None, firmware: str | None) -> bool:
    """Apply vendor family floors before the hardware-accepted allowlist."""
    normalized = (model or "").strip().upper()
    version = parse_firmware(firmware)
    if not normalized or version is None or normalized.startswith("SURTD"):
        return False
    if re.match(r"^SMT\d+RM1U(?:\b|$)", normalized):
        return False
    if normalized.startswith("SMT"):
        return version >= (9, 0)
    if normalized.startswith("SMX"):
        return version >= (10, 0)
    if normalized.startswith("SRT"):
        return True
    return normalized in SRC_MODELS


def release_model_supported(
    model: str | None,
    firmware: str | None,
    allowlist: Collection[tuple[str, tuple[int, ...]]] = RELEASE_SUPPORTED_MODELS,
) -> bool:
    """Require exact hardware-accepted identity in addition to family eligibility."""
    normalized = (model or "").strip().upper()
    version = parse_firmware(firmware)
    return bool(
        version is not None
        and vendor_family_eligible(normalized, firmware)
        and (normalized, version) in allowlist
    )


def protocol_constants_valid(values: dict[int, tuple[int, ...]]) -> bool:
    """Check the documented byte-order constants; map ID is deliberately absent."""
    return all(
        values.get(address) == expected for address, expected in PROTOCOL_TESTS.items()
    )


def encode_int32(value: int) -> tuple[int, int]:
    """Encode one signed 32-bit value in Modbus word order."""
    if not -(2**31) <= value <= 2**31 - 1:
        raise ValueError("signed_32_bit_range")
    return ((value >> 16) & 0xFFFF, value & 0xFFFF)


def build_outlet_command(action: OutletAction, target: OutletTarget) -> tuple[int, int]:
    """Build one immediate outlet command with InternalNetwork1 as source."""
    try:
        action_bit = OUTLET_ACTION_BITS[action]
        target_bit = OUTLET_TARGET_BITS[target]
    except (KeyError, TypeError) as err:
        raise ValueError("invalid_outlet_command") from err
    value = (1 << action_bit) | (1 << target_bit) | (1 << 17)
    return ((value >> 16) & 0xFFFF, value & 0xFFFF)


@dataclass(frozen=True)
class OutletStatus:
    """Decoded readable outlet state and conflict bits."""

    raw: int
    is_on: bool
    is_off: bool
    pending: bool
    process: str | None
    valid: bool


def decode_outlet_status(raw: int) -> OutletStatus:
    process_bits = [bit for bit in (2, 3, 4) if raw & (1 << bit)]
    state_bits = [bit for bit in (0, 1) if raw & (1 << bit)]
    process_names = {2: "reboot", 3: "shutdown", 4: "sleep"}
    reserved = raw & ~0x7F9F
    return OutletStatus(
        raw=raw,
        is_on=bool(raw & 1),
        is_off=bool(raw & 2),
        pending=bool(raw & 0x3F9C),
        process=process_names.get(process_bits[0]) if len(process_bits) == 1 else None,
        valid=not reserved and len(state_bits) == 1 and len(process_bits) <= 1,
    )


@dataclass(frozen=True)
class OperationStatus:
    raw: int
    state: str
    active: bool
    valid: bool


def decode_operation_status(raw: int, valid_mask: int = 0x0FFF) -> OperationStatus:
    names = ("pending", "in_progress", "passed", "failed", "refused", "aborted")
    set_states = [name for bit, name in enumerate(names) if raw & (1 << bit)]
    return OperationStatus(
        raw=raw,
        state=set_states[0] if len(set_states) == 1 else "unknown",
        active=bool(raw & 0x0003),
        valid=raw != 0xFFFF and not bool(raw & ~valid_mask) and len(set_states) <= 1,
    )


def decode_battery_test_status(raw: int) -> OperationStatus:
    """Decode 0x0017, whose bits 12-15 are reserved."""
    return decode_operation_status(raw, 0x0FFF)


def decode_runtime_calibration_status(raw: int) -> OperationStatus:
    """Decode 0x0018, whose result modifiers use all 16 bits."""
    return decode_operation_status(raw, 0xFFFF)


@dataclass(frozen=True)
class AlarmStatus:
    raw: int
    alarm_active: bool
    muted: bool
    valid: bool


def decode_alarm_status(raw: int) -> AlarmStatus:
    return AlarmStatus(raw, bool(raw & 2), bool(raw & 4), not bool(raw & 0xFFF0))


def outlet_precondition(
    action: OutletAction,
    target: OutletTarget,
    statuses: dict[OutletTarget, OutletStatus],
) -> str | None:
    """Return a translation key when an outlet action is unsafe."""
    status = statuses.get(target)
    if status is None or not status.valid:
        return "write_state_unavailable"
    if action == OutletAction.CANCEL:
        return None if status.pending else "outlet_nothing_to_cancel"
    if status.pending:
        return "outlet_operation_pending"
    if action == OutletAction.ON:
        if not status.is_off:
            return "outlet_already_on"
        mog = statuses.get(OutletTarget.MOG)
        if target != OutletTarget.MOG and (mog is None or not mog.is_on):
            return "outlet_mog_must_be_on"
        return None
    if not status.is_on:
        return "outlet_already_off"
    if action == OutletAction.OFF and target == OutletTarget.MOG:
        if any(
            other.is_on
            for other_target, other in statuses.items()
            if other_target != OutletTarget.MOG and other.valid
        ):
            return "outlet_sog_must_be_off"
    return None


def operation_precondition(action: str, status: OperationStatus) -> str | None:
    if not status.valid:
        return "write_state_unavailable"
    if action == "start":
        return "operation_already_active" if status.active else None
    if action == "abort":
        return None if status.active else "operation_not_active"
    return "invalid_operation"


def alarm_precondition(mute: bool, status: AlarmStatus) -> str | None:
    if not status.valid:
        return "write_state_unavailable"
    if mute:
        return None if status.alarm_active else "alarm_not_active"
    return None if status.muted else "alarm_not_muted"


def _response_ok(response: Any) -> bool:
    if response is None:
        return False
    for name in ("isError", "is_error"):
        predicate = getattr(response, name, None)
        if callable(predicate) and predicate():
            return False
    retries = getattr(response, "retries", 0)
    return retries in (None, 0)


def validate_write_single_response(response: Any, address: int, value: int) -> bool:
    """Validate a function-6 exact address/value echo."""
    registers = getattr(response, "registers", None)
    echoed_value = getattr(response, "value", None)
    if echoed_value is None and isinstance(registers, (list, tuple)) and registers:
        echoed_value = registers[0]
    return bool(
        _response_ok(response)
        and getattr(response, "address", None) == address
        and echoed_value == value
    )


def validate_write_multiple_response(response: Any, address: int, count: int) -> bool:
    """Validate a function-16 exact address/count echo."""
    return bool(
        _response_ok(response)
        and getattr(response, "address", None) == address
        and getattr(response, "count", None) == count
    )
