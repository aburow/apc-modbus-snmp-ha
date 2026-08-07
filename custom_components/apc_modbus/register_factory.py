# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Factory pattern for selecting device-type-specific registers."""

from __future__ import annotations

import logging
from typing import Any

from .device_types import APCDeviceType
from . import registers_smart_ups

_LOGGER = logging.getLogger(__name__)

CORE_REGISTER_KEYS_BY_DEVICE: dict[APCDeviceType, set[str]] = {
    APCDeviceType.SMART_UPS: {
        "runtime_remaining",
        "battery_state_of_charge",
        "input_voltage",
        "actual_output_voltage",
        "load_percent",
        "input_frequency",
        "status_word_3",  # ups_online / ups_on_battery / ups_overload bits
    },
    APCDeviceType.SMT_UPS: {
        "runtime_remaining",
        "battery_state_of_charge",
        "input_voltage",
        "output_voltage",
        "output_load_percent",
        "output_frequency",
        "ups_status_bf",  # online/battery/bypass/overload bits
    },
    APCDeviceType.SMARTCONNECT_UPS: {
        "runtime_remaining",
        "battery_state_of_charge",
        "input_voltage",
        "output_voltage",
        "output_load_percent",
        "output_frequency",
        "ups_status_bf",  # online/battery/bypass/overload bits
    },
}


def get_registers_for_device(
    device_type: APCDeviceType,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Get registers, blocks, and map for the specified device type.

    Args:
        device_type: The detected or configured device type

    Returns:
        Tuple of (REGISTERS, REGISTER_BLOCKS, REGISTER_MAP)
    """
    if device_type == APCDeviceType.SMART_UPS:
        return (
            registers_smart_ups.REGISTERS,
            registers_smart_ups.REGISTER_BLOCKS,
            registers_smart_ups.REGISTER_MAP,
        )
    elif device_type == APCDeviceType.SMT_UPS:
        try:
            from . import registers_smt_ups

            return (
                registers_smt_ups.REGISTERS,
                registers_smt_ups.REGISTER_BLOCKS,
                registers_smt_ups.REGISTER_MAP,
            )
        except ImportError:
            _LOGGER.warning(
                "SMT UPS register module not available, falling back to Smart-UPS"
            )
            return (
                registers_smart_ups.REGISTERS,
                registers_smart_ups.REGISTER_BLOCKS,
                registers_smart_ups.REGISTER_MAP,
            )
    elif device_type == APCDeviceType.SMARTCONNECT_UPS:
        try:
            from . import registers_smt_ups

            registers = [
                descriptor
                for descriptor in registers_smt_ups.REGISTERS
                if descriptor["key"]
                not in registers_smt_ups.SMARTCONNECT_UNSUPPORTED_REGISTER_KEYS
            ]
            return (
                registers,
                _build_blocks_from_registers(registers),
                {descriptor["address"]: descriptor for descriptor in registers},
            )
        except ImportError:
            _LOGGER.warning(
                "SMT UPS register module not available, falling back to Smart-UPS"
            )
            return (
                registers_smart_ups.REGISTERS,
                registers_smart_ups.REGISTER_BLOCKS,
                registers_smart_ups.REGISTER_MAP,
            )
    elif device_type == APCDeviceType.RACK_PDU:
        # Import here to avoid circular imports and lazy-load Rack PDU registers
        try:
            from . import registers_rack_pdu

            return (
                registers_rack_pdu.REGISTERS,
                registers_rack_pdu.REGISTER_BLOCKS,
                registers_rack_pdu.REGISTER_MAP,
            )
        except ImportError:
            _LOGGER.warning(
                "Rack PDU register module not available, falling back to Smart-UPS"
            )
            return (
                registers_smart_ups.REGISTERS,
                registers_smart_ups.REGISTER_BLOCKS,
                registers_smart_ups.REGISTER_MAP,
            )
    else:
        # Unknown type defaults to Smart-UPS
        _LOGGER.debug("Unknown device type %s, defaulting to Smart-UPS", device_type)
        return (
            registers_smart_ups.REGISTERS,
            registers_smart_ups.REGISTER_BLOCKS,
            registers_smart_ups.REGISTER_MAP,
        )


def _build_blocks_from_registers(
    registers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build compact contiguous blocks from register descriptors."""
    if not registers:
        return []

    ordered = sorted(registers, key=lambda descriptor: int(descriptor["address"]))
    blocks: list[dict[str, Any]] = []
    block_index = 1

    current_start = int(ordered[0]["address"])
    current_end = current_start + int(ordered[0].get("count", 1)) - 1
    current_registers = [current_start]

    for descriptor in ordered[1:]:
        descriptor_start = int(descriptor["address"])
        descriptor_end = descriptor_start + int(descriptor.get("count", 1)) - 1

        if descriptor_start <= current_end + 1:
            current_end = max(current_end, descriptor_end)
            current_registers.append(descriptor_start)
            continue

        blocks.append(
            {
                "name": f"core_block_{block_index}",
                "start_address": current_start,
                "count": current_end - current_start + 1,
                "registers": current_registers,
            }
        )
        block_index += 1
        current_start = descriptor_start
        current_end = descriptor_end
        current_registers = [descriptor_start]

    blocks.append(
        {
            "name": f"core_block_{block_index}",
            "start_address": current_start,
            "count": current_end - current_start + 1,
            "registers": current_registers,
        }
    )
    return blocks


def build_core_register_profile(
    device_type: APCDeviceType,
    registers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """Build a reduced core register profile for UPS device families."""
    core_keys = CORE_REGISTER_KEYS_BY_DEVICE.get(device_type)
    if not core_keys:
        register_map = {
            int(descriptor["address"]): descriptor for descriptor in registers
        }
        return registers, _build_blocks_from_registers(registers), register_map

    filtered_registers = [
        descriptor for descriptor in registers if descriptor.get("key") in core_keys
    ]
    register_map = {
        int(descriptor["address"]): descriptor for descriptor in filtered_registers
    }
    return (
        filtered_registers,
        _build_blocks_from_registers(filtered_registers),
        register_map,
    )
