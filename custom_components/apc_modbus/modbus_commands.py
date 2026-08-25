# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixed APC command encodings used by the V2 transport command seam."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModbusCommand:
    """One documented Modbus register command."""

    key: str
    name: str
    address: int
    words: tuple[int, ...]


COMMANDS = {
    command.key: command
    for command in (
        ModbusCommand("bypass_enter", "Enter bypass", 0x0600, (0, 1 << 4)),
        ModbusCommand("bypass_exit", "Return from bypass", 0x0600, (0, 1 << 5)),
        ModbusCommand("battery_test_start", "Start battery self-test", 0x0605, (1,)),
        ModbusCommand("battery_test_abort", "Abort battery self-test", 0x0605, (2,)),
        ModbusCommand("calibration_start", "Start runtime calibration", 0x0606, (1,)),
        ModbusCommand("calibration_abort", "Abort runtime calibration", 0x0606, (2,)),
        ModbusCommand("alarm_mute", "Mute alarms", 0x0607, (4,)),
        ModbusCommand("alarm_cancel_mute", "Cancel alarm mute", 0x0607, (8,)),
    )
}

OUTLET_ACTION_BITS = {
    "outlet_cancel": 0,
    "outlet_on": 1,
    "outlet_off": 2,
    "outlet_shutdown": 3,
    "outlet_reboot": 4,
}
OUTLET_TARGET_BITS = {
    "main_outlet_group": 8,
    "switched_outlet_group_1": 9,
    "switched_outlet_group_2": 10,
    "switched_outlet_group_3": 11,
}


def get_command(key: str, target: str | None = None) -> ModbusCommand:
    """Return a fixed command; outlet commands require a documented target."""
    if key in COMMANDS and target is None:
        return COMMANDS[key]
    if key not in OUTLET_ACTION_BITS or target not in OUTLET_TARGET_BITS:
        raise ValueError("unsupported_command")
    value = (
        (1 << OUTLET_ACTION_BITS[key]) | (1 << OUTLET_TARGET_BITS[target]) | (1 << 17)
    )
    return ModbusCommand(
        f"{key}_{target}",
        f"{key.replace('_', ' ').title()}: {target.replace('_', ' ').title()}",
        0x0602,
        ((value >> 16) & 0xFFFF, value & 0xFFFF),
    )
