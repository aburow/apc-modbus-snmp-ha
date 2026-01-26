# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Factory pattern for selecting device-type-specific registers."""

from __future__ import annotations

import logging
from typing import Any

from .device_types import APCDeviceType
from . import registers_smart_ups

_LOGGER = logging.getLogger(__name__)


def get_registers_for_device(device_type: APCDeviceType) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]]]:
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
            _LOGGER.warning("Rack PDU register module not available, falling back to Smart-UPS")
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
