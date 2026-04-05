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

# APC Smart-UPS SNMP OIDs (1.3.6.1.4.1.318.1.1.1.*)
SMARTUPS_OID_MODEL = "1.3.6.1.4.1.318.1.1.1.1.1.1.0"
SMARTUPS_OID_SERIAL = "1.3.6.1.4.1.318.1.1.1.1.2.3.0"
SMARTUPS_OID_FIRMWARE = "1.3.6.1.4.1.318.1.1.1.1.2.1.0"
SMARTUPS_OID_FIRMWARE_DATE = "1.3.6.1.4.1.318.1.1.1.1.2.2.0"

# APC Rack PDU SNMP OIDs (1.3.6.1.4.1.318.1.1.12.1.*)
RACKPDU_OID_MODEL = "1.3.6.1.4.1.318.1.1.12.1.5.0"
RACKPDU_OID_SERIAL = "1.3.6.1.4.1.318.1.1.12.1.6.0"
RACKPDU_OID_FIRMWARE = "1.3.6.1.4.1.318.1.1.12.1.3.0"
RACKPDU_OID_FIRMWARE_DATE = "1.3.6.1.4.1.318.1.1.12.1.4.0"

# APC Universal I/O sensor status table (PowerNet-MIB)
# Index 1/2 typically correspond to UIO ports 1/2.
UIO_SENSOR_STATUS_TEMP_C_BASE = "1.3.6.1.4.1.318.1.1.25.1.2.1.6"
UIO_SENSOR_STATUS_HUMIDITY_BASE = "1.3.6.1.4.1.318.1.1.25.1.2.1.7"


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

        # Create UDP transport target
        target = await UdpTransportTarget.create(
            (host, 161), timeout=timeout, retries=3
        )

        # Execute SNMP GET command
        errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
            SnmpEngine(),
            CommunityData(community, mpModel=1),  # SNMPv2c
            target,
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )

        if errorIndication:
            _LOGGER.debug("SNMP error from %s (OID %s): %s", host, oid, errorIndication)
            return None
        elif errorStatus:
            _LOGGER.debug(
                "SNMP error status from %s (OID %s): %s at index %s",
                host,
                oid,
                errorStatus.prettyPrint(),
                errorIndex,
            )
            return None
        else:
            for varBind in varBinds:
                value = str(varBind[1])
                _LOGGER.debug(
                    "SNMP query succeeded: %s=%s",
                    oid,
                    value[:50] if len(value) > 50 else value,
                )
                return value

        _LOGGER.debug("SNMP query returned no value for OID %s", oid)
        return None

    except asyncio.TimeoutError:
        _LOGGER.warning(
            "SNMP query to %s timed out after %ds for OID %s", host, timeout, oid
        )
        return None
    except (OSError, TimeoutError, RuntimeError, ValueError) as err:
        _LOGGER.debug(
            "SNMP query failed for %s (OID %s): %s (%s)",
            host,
            oid,
            err,
            type(err).__name__,
        )
        return None


async def async_get_device_metadata(
    host: str,
    community: str = "public",
    device_type: APCDeviceType | None = None,
) -> dict[str, Any]:
    """Query all device metadata via SNMP.

    Args:
        host: Device IP address
        community: SNMP community string (default: "public")
        device_type: Type of APC device. `None` queries both Smart-UPS and
            Rack PDU OIDs and picks the best metadata match.

    Returns dict with keys: model, serial_number, firmware_version, firmware_date
    All values are None if SNMP fails.
    """
    _LOGGER.debug(
        "Querying SNMP metadata from %s (community: %s, device_type: %s)",
        host,
        community,
        device_type.value if device_type else "auto",
    )

    async def query_metadata_for_type(query_type: APCDeviceType) -> dict[str, Any]:
        if query_type == APCDeviceType.RACK_PDU:
            oid_model = RACKPDU_OID_MODEL
            oid_serial = RACKPDU_OID_SERIAL
            oid_firmware = RACKPDU_OID_FIRMWARE
            oid_firmware_date = RACKPDU_OID_FIRMWARE_DATE
        else:
            oid_model = SMARTUPS_OID_MODEL
            oid_serial = SMARTUPS_OID_SERIAL
            oid_firmware = SMARTUPS_OID_FIRMWARE
            oid_firmware_date = SMARTUPS_OID_FIRMWARE_DATE

        results = await asyncio.gather(
            async_get_snmp_value(host, oid_model, community),
            async_get_snmp_value(host, oid_serial, community),
            async_get_snmp_value(host, oid_firmware, community),
            async_get_snmp_value(host, oid_firmware_date, community),
            return_exceptions=True,
        )
        model, serial, firmware, fw_date = [
            r if not isinstance(r, Exception) else None for r in results
        ]
        return {
            "model": model,
            "serial_number": serial,
            "firmware_version": firmware,
            "firmware_date": fw_date,
        }

    if device_type in (None, APCDeviceType.UPS, APCDeviceType.UNKNOWN):
        smartups_metadata, rackpdu_metadata = await asyncio.gather(
            query_metadata_for_type(APCDeviceType.SMART_UPS),
            query_metadata_for_type(APCDeviceType.RACK_PDU),
        )
        metadata = (
            rackpdu_metadata if rackpdu_metadata.get("model") else smartups_metadata
        )
    else:
        metadata = await query_metadata_for_type(device_type)

    _LOGGER.debug("SNMP metadata retrieved: %s", metadata)
    return metadata


def get_device_metadata_sync(
    host: str,
    community: str = "public",
    device_type: APCDeviceType | None = None,
) -> dict[str, Any]:
    """Run SNMP metadata query in a dedicated event loop (sync wrapper)."""
    return asyncio.run(async_get_device_metadata(host, community, device_type))


def _parse_external_temp_c(value: str | None) -> float | None:
    """Parse APC external temperature (Celsius) from SNMP value.

    Some devices report whole degrees, others report tenths of a degree.
    """
    if value is None:
        return None
    try:
        raw = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    if raw < 0:
        return None
    if raw > 120:
        return raw / 10.0
    return float(raw)


def _parse_external_humidity_pct(value: str | None) -> float | None:
    """Parse APC external humidity percentage from SNMP value.

    Some devices report whole %, others report tenths of a percent.
    """
    if value is None:
        return None
    try:
        raw = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if raw < 0:
        return None
    if raw > 100:
        return raw / 10.0
    return float(raw)


async def async_get_external_probe_data(
    host: str, community: str = "public"
) -> dict[str, float | None]:
    """Query APC external probe values via SNMP.

    Returns keys:
      - snmp_external_temp_1
      - snmp_external_humidity_1
      - snmp_external_temp_2
      - snmp_external_humidity_2
    """
    # Different APC/NMC generations expose UIO values at slightly different
    # instance depths. Try the two known index layouts per probe.
    oid_candidates = {
        "snmp_external_temp_1": [
            f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.1.1",
            f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.1",
        ],
        "snmp_external_humidity_1": [
            f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.1.1",
            f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.1",
        ],
        "snmp_external_temp_2": [
            f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.2.1",
            f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.2",
        ],
        "snmp_external_humidity_2": [
            f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.2.1",
            f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.2",
        ],
    }

    parsed: dict[str, float | None] = {}
    for key, candidates in oid_candidates.items():
        raw_value: str | None = None
        for oid in candidates:
            raw_value = await async_get_snmp_value(host, oid, community)
            if raw_value is not None:
                break

        if key.startswith("snmp_external_temp"):
            parsed[key] = _parse_external_temp_c(raw_value)
        else:
            parsed[key] = _parse_external_humidity_pct(raw_value)

    return parsed


def get_external_probe_data_sync(
    host: str,
    community: str = "public",
) -> dict[str, float | None]:
    """Run external probe SNMP query in a dedicated event loop (sync wrapper)."""
    return asyncio.run(async_get_external_probe_data(host, community))


def detect_device_type(model_string: str | None) -> APCDeviceType:
    """Detect device type from SNMP model string.

    Patterns:
    - "AP8*" or "APDU*" or "*Rack PDU*" -> RACK_PDU
    - "SMT*", "SMX*", "SRT*", or matching Smart-UPS SMT/SMX/SRT -> SMT_UPS
    - "Smart-UPS*" / "SMART UPS*" (legacy families) -> SMART_UPS
    - None/unknown -> SMART_UPS (backward compatibility default)

    Args:
        model_string: The model string from SNMP query

    Returns:
        APCDeviceType enum indicating the device type
    """
    if not model_string:
        return APCDeviceType.SMART_UPS

    model_upper = model_string.upper()

    # Check for Rack PDU patterns
    if (
        "AP8" in model_upper
        or model_upper.startswith("APDU")
        or "RACK PDU" in model_upper
    ):
        return APCDeviceType.RACK_PDU

    # Check for SMT/SMX/SRT patterns (must come before generic Smart-UPS check)
    if (
        model_upper.startswith("SMT")
        or model_upper.startswith("SMX")
        or model_upper.startswith("SRT")
        or "SMART-UPS X" in model_upper
        or "SMART UPS X" in model_upper
        or "SMART-UPS SMT" in model_upper
        or "SMART-UPS SMX" in model_upper
        or "SMART-UPS SRT" in model_upper
    ):
        return APCDeviceType.SMT_UPS

    # Check for legacy Smart-UPS patterns (SUA, SU, etc.)
    if "SMART-UPS" in model_upper or "SMART UPS" in model_upper:
        return APCDeviceType.SMART_UPS

    return APCDeviceType.SMART_UPS  # Safe default
