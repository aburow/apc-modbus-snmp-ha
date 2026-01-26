# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""SNMP helper for APC UPS device metadata retrieval."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    getCmd,
)

from .device_types import APCDeviceType

_LOGGER = logging.getLogger(__name__)

# APC UPS SNMP OIDs
OID_MODEL = "1.3.6.1.4.1.318.1.1.1.1.1.1.0"
OID_SERIAL = "1.3.6.1.4.1.318.1.1.1.1.2.3.0"
OID_FIRMWARE = "1.3.6.1.4.1.318.1.1.1.1.2.1.0"
OID_FIRMWARE_DATE = "1.3.6.1.4.1.318.1.1.1.1.2.2.0"


async def async_get_snmp_value(
    host: str, oid: str, community: str = "public", timeout: int = 5
) -> str | None:
    """Query single SNMP OID and return string value.

    Args:
        host: IP address of SNMP device
        oid: SNMP OID to query
        community: SNMP community string (default: "public")
        timeout: Query timeout in seconds (default: 5)

    Returns:
        String value from OID or None if query failed
    """
    try:
        _LOGGER.debug("SNMP query to %s OID %s (timeout=%ds)", host, oid, timeout)
        # Use asyncio.wait_for to enforce timeout on the SNMP query
        iterator = await asyncio.wait_for(
            getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),  # SNMPv2c
                UdpTransportTarget(host, 161),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            ),
            timeout=timeout,
        )

        errorIndication, errorStatus, errorIndex, varBinds = iterator

        if errorIndication:
            _LOGGER.debug("SNMP error from %s (OID %s): %s", host, oid, errorIndication)
            return None
        elif errorStatus:
            _LOGGER.debug("SNMP error status from %s (OID %s): %s at index %s", host, oid, errorStatus, errorIndex)
            return None
        else:
            for varBind in varBinds:
                value = str(varBind[1])
                _LOGGER.debug("SNMP query succeeded: %s=%s", oid, value[:50] if len(value) > 50 else value)
                return value

        _LOGGER.debug("SNMP query returned no value for OID %s", oid)
        return None

    except asyncio.TimeoutError:
        _LOGGER.warning("SNMP query to %s timed out after %ds for OID %s", host, timeout, oid)
        return None
    except Exception as err:
        _LOGGER.debug("SNMP query failed for %s (OID %s): %s (%s)", host, oid, err, type(err).__name__)
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
