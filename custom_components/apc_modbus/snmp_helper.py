# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""SNMP helper for APC UPS device metadata retrieval."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
)

from .device_types import APCDeviceType

_LOGGER = logging.getLogger(__name__)

# APC UPS SNMP OIDs
OID_MODEL = "1.3.6.1.4.1.318.1.1.1.1.1.1.0"
OID_SERIAL = "1.3.6.1.4.1.318.1.1.1.1.2.3.0"
OID_FIRMWARE = "1.3.6.1.4.1.318.1.1.1.1.2.1.0"
OID_FIRMWARE_DATE = "1.3.6.1.4.1.318.1.1.1.1.2.2.0"


async def async_get_snmp_value(
    host: str, oid: str, community: str = "public", timeout: int = 3
) -> str | None:
    """Query single SNMP OID and return string value."""
    try:
        iterator = await get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),  # SNMPv2c
            UdpTransportTarget((host, 161), timeout=timeout),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )

        errorIndication, errorStatus, errorIndex, varBinds = iterator

        if errorIndication:
            _LOGGER.debug("SNMP error: %s", errorIndication)
            return None
        elif errorStatus:
            _LOGGER.debug("SNMP error status: %s at %s", errorStatus, errorIndex)
            return None
        else:
            for varBind in varBinds:
                return str(varBind[1])

    except Exception as err:
        _LOGGER.debug("SNMP query failed for %s: %s", oid, err)
        return None


async def async_get_device_metadata(
    host: str, community: str = "public"
) -> dict[str, Any]:
    """Query all device metadata via SNMP.

    Args:
        host: UPS IP address
        community: SNMP community string (default: "public")

    Returns dict with keys: model, serial_number, firmware_version, firmware_date
    All values are None if SNMP fails.
    """
    _LOGGER.debug("Querying SNMP metadata from %s (community: %s)", host, community)

    # Query all OIDs in parallel
    results = await asyncio.gather(
        async_get_snmp_value(host, OID_MODEL, community),
        async_get_snmp_value(host, OID_SERIAL, community),
        async_get_snmp_value(host, OID_FIRMWARE, community),
        async_get_snmp_value(host, OID_FIRMWARE_DATE, community),
        return_exceptions=True,
    )

    # Handle exceptions in results
    model, serial, firmware, fw_date = [
        r if not isinstance(r, Exception) else None for r in results
    ]

    metadata = {
        "model": model,
        "serial_number": serial,
        "firmware_version": firmware,
        "firmware_date": fw_date,
    }

    _LOGGER.debug("SNMP metadata retrieved: %s", metadata)
    return metadata


def detect_device_type(model_string: str | None) -> APCDeviceType:
    """Detect device type from SNMP model string.

    Patterns:
    - "AP8*" or "APDU*" or "*Rack PDU*" → RACK_PDU
    - "Smart-UPS*" or "SMART-UPS*" → SMART_UPS
    - None/unknown → SMART_UPS (backward compatibility default)

    Args:
        model_string: The model string from SNMP query

    Returns:
        APCDeviceType enum indicating the device type
    """
    if not model_string:
        return APCDeviceType.SMART_UPS

    model_upper = model_string.upper()

    # Check for Rack PDU patterns
    if "AP8" in model_upper or model_upper.startswith("APDU") or "RACK PDU" in model_upper:
        return APCDeviceType.RACK_PDU

    # Check for Smart-UPS patterns
    if "SMART-UPS" in model_upper or "SMART UPS" in model_upper:
        return APCDeviceType.SMART_UPS

    return APCDeviceType.SMART_UPS  # Safe default
