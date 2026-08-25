# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""SNMP helper for APC UPS device metadata retrieval."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any
from collections.abc import Callable

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    get_cmd,
    set_cmd,
)
from pysnmp.proto.rfc1902 import Integer

from .device_types import APCDeviceType

_LOGGER = logging.getLogger(__name__)
NUMERIC_VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

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
# Input frequency candidates for AP9640-class cards.
# APC enterprise OID first, then RFC1628 UPS-MIB line 1 frequency.
SMARTUPS_OID_INPUT_FREQUENCY = "1.3.6.1.4.1.318.1.1.1.3.2.4.0"
UPS_MIB_OID_INPUT_FREQUENCY_LINE1 = "1.3.6.1.2.1.33.1.3.3.1.2.1"
SELF_TEST_OIDS = {
    "snmp_self_test_schedule": "1.3.6.1.4.1.318.1.1.1.7.2.1.0",
    "snmp_self_test_result": "1.3.6.1.4.1.318.1.1.1.7.2.3.0",
    "snmp_last_self_test_date": "1.3.6.1.4.1.318.1.1.1.7.2.4.0",
    "snmp_self_test_time": "1.3.6.1.4.1.318.1.1.1.7.2.8.0",
    "snmp_self_test_day": "1.3.6.1.4.1.318.1.1.1.7.2.9.0",
    "snmp_runtime_calibration_status": "1.3.6.1.4.1.318.1.1.1.7.2.6.0",
}
SELF_TEST_TIME_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
SELF_TEST_DATE_RE = re.compile(r"\d{2}/\d{2}/(?:\d{2}|\d{4})")


async def async_set_snmp_integer(
    host: str, oid: str, value: int, community: str, snmp_port: int = 161
) -> None:
    """Send one SNMPv2c SET request without retrying it."""
    target = await UdpTransportTarget.create((host, snmp_port), timeout=5, retries=0)
    error, status, index, _ = await set_cmd(
        SnmpEngine(),
        CommunityData(community, mpModel=1),
        target,
        ContextData(),
        ObjectType(ObjectIdentity(oid), Integer(value)),
    )
    if error or status:
        detail = str(error or status.prettyPrint())
        raise RuntimeError(f"snmp_set_failed:{detail}:{index}")


def _dedupe_oids_preserve_order(oids: list[str]) -> list[str]:
    """Return unique OIDs in first-seen order."""
    seen: set[str] = set()
    unique: list[str] = []
    for oid in oids:
        if oid in seen:
            continue
        seen.add(oid)
        unique.append(oid)
    return unique


async def _fetch_snmp_value_map(
    host: str, community: str, oids: list[str], snmp_port: int = 161
) -> dict[str, str | None]:
    """Fetch OIDs once and return an OID->value map."""
    unique_oids = _dedupe_oids_preserve_order(oids)
    if not unique_oids:
        return {}
    results = await asyncio.gather(
        *[
            async_get_snmp_value(host, oid, community, snmp_port=snmp_port)
            for oid in unique_oids
        ],
        return_exceptions=True,
    )
    value_map: dict[str, str | None] = {}
    for oid, raw in zip(unique_oids, results, strict=True):
        value_map[oid] = raw if not isinstance(raw, Exception) else None
    return value_map


def _select_first_present_candidate_from_map(
    candidates: list[str], value_map: dict[str, str | None]
) -> str | None:
    """Pick the first candidate whose fetched value is present."""
    for oid in candidates:
        if value_map.get(oid) is not None:
            return oid
    return None


def _select_first_usable_candidate_from_map(
    candidates: list[str],
    value_map: dict[str, str | None],
    parser: Callable[[str | None], float | None],
) -> str | None:
    """Pick the first candidate whose fetched value parses as usable."""
    for oid in candidates:
        if parser(value_map.get(oid)) is not None:
            return oid
    return None


async def async_get_snmp_value(
    host: str,
    oid: str,
    community: str = "public",
    timeout: int = 5,
    snmp_port: int = 161,
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
            (host, snmp_port), timeout=timeout, retries=3
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
        _LOGGER.debug(
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
    snmp_port: int = 161,
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
        "Querying SNMP metadata from %s (device type: %s)",
        host,
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
            async_get_snmp_value(host, oid_model, community, snmp_port=snmp_port),
            async_get_snmp_value(host, oid_serial, community, snmp_port=snmp_port),
            async_get_snmp_value(host, oid_firmware, community, snmp_port=snmp_port),
            async_get_snmp_value(
                host, oid_firmware_date, community, snmp_port=snmp_port
            ),
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
    snmp_port: int = 161,
) -> dict[str, Any]:
    """Run SNMP metadata query in a dedicated event loop (sync wrapper)."""
    return asyncio.run(
        async_get_device_metadata(host, community, device_type, snmp_port)
    )


def _parse_external_temp_c(value: str | None) -> float | None:
    """Parse APC external temperature (Celsius) from SNMP value.

    Some devices report whole degrees, others report tenths of a degree.
    """
    if value is None:
        return None
    match = NUMERIC_VALUE_RE.search(str(value))
    if not match:
        return None
    try:
        raw = float(match.group(0))
    except (TypeError, ValueError):
        return None

    if raw < 0:
        return None
    if raw > 120:
        return raw / 10.0
    return raw


def _parse_external_humidity_pct(value: str | None) -> float | None:
    """Parse APC external humidity percentage from SNMP value.

    Some devices report whole %, others report tenths of a percent.
    """
    if value is None:
        return None
    match = NUMERIC_VALUE_RE.search(str(value))
    if not match:
        return None
    try:
        raw = float(match.group(0))
    except (TypeError, ValueError):
        return None
    if raw < 0:
        return None
    if raw > 100:
        return raw / 10.0
    return raw


def _parse_frequency_hz(value: str | None) -> float | None:
    """Parse input frequency from SNMP value.

    APC and UPS-MIB devices may report frequency as either whole Hz or tenths Hz.
    """
    if value is None:
        return None
    try:
        raw = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    if raw > 400:
        return raw / 10.0
    return raw


def _parse_self_test_date(value: str | None) -> date | None:
    """Parse the PowerNet-MIB's mm/dd/yy or mm/dd/yyyy self-test date."""
    if not value:
        return None
    value = value.strip()
    if not SELF_TEST_DATE_RE.fullmatch(value):
        return None
    try:
        return datetime.strptime(
            value, "%m/%d/%Y" if len(value) == 10 else "%m/%d/%y"
        ).date()
    except ValueError:
        return None


def _parse_self_test_time(value: str | None) -> str | None:
    """Validate a timezone-free PowerNet-MIB self-test time."""
    if not value:
        return None
    value = value.strip()
    return value if SELF_TEST_TIME_RE.fullmatch(value) else None


def _parse_self_test_enum(value: str | None) -> int | None:
    """Parse a PowerNet-MIB self-test enum code."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def async_get_self_test_data(
    host: str, community: str = "public", snmp_port: int = 161
) -> dict[str, int | str | date | None]:
    """Query and decode Smart-UPS self-test state and schedule data."""
    value_map = await _fetch_snmp_value_map(
        host, community, list(SELF_TEST_OIDS.values()), snmp_port=snmp_port
    )
    return {
        "snmp_self_test_schedule": _parse_self_test_enum(
            value_map.get(SELF_TEST_OIDS["snmp_self_test_schedule"])
        ),
        "snmp_self_test_result": _parse_self_test_enum(
            value_map.get(SELF_TEST_OIDS["snmp_self_test_result"])
        ),
        "snmp_last_self_test_date": _parse_self_test_date(
            value_map.get(SELF_TEST_OIDS["snmp_last_self_test_date"])
        ),
        "snmp_self_test_time": _parse_self_test_time(
            value_map.get(SELF_TEST_OIDS["snmp_self_test_time"])
        ),
        "snmp_self_test_day": _parse_self_test_enum(
            value_map.get(SELF_TEST_OIDS["snmp_self_test_day"])
        ),
        "snmp_runtime_calibration_status": _parse_self_test_enum(
            value_map.get(SELF_TEST_OIDS["snmp_runtime_calibration_status"])
        ),
    }


def get_self_test_data_sync(
    host: str, community: str = "public", snmp_port: int = 161
) -> dict[str, int | str | date | None]:
    """Run the self-test SNMP query in a dedicated event loop."""
    return asyncio.run(async_get_self_test_data(host, community, snmp_port))


async def async_get_external_probe_data(
    host: str, community: str = "public", snmp_port: int = 161
) -> dict[str, float | None]:
    """Query APC external probe values via SNMP.

    Returns keys:
      - snmp_external_temp_1
      - snmp_external_humidity_1
      - snmp_external_temp_2
      - snmp_external_humidity_2
      - snmp_input_frequency
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
        "snmp_input_frequency": [
            SMARTUPS_OID_INPUT_FREQUENCY,
            UPS_MIB_OID_INPUT_FREQUENCY_LINE1,
        ],
    }

    all_candidates = [
        oid for candidates in oid_candidates.values() for oid in candidates
    ]
    value_map = await _fetch_snmp_value_map(
        host, community, all_candidates, snmp_port=snmp_port
    )

    parsed: dict[str, float | None] = {}
    for key, candidates in oid_candidates.items():
        selected_oid = _select_first_present_candidate_from_map(candidates, value_map)
        raw_value = value_map.get(selected_oid) if selected_oid else None
        if key == "snmp_input_frequency":
            parsed[key] = _parse_frequency_hz(raw_value)
        elif key.startswith("snmp_external_temp"):
            parsed[key] = _parse_external_temp_c(raw_value)
        else:
            parsed[key] = _parse_external_humidity_pct(raw_value)

    return parsed


def get_external_probe_data_sync(
    host: str,
    community: str = "public",
    snmp_port: int = 161,
) -> dict[str, float | None]:
    """Run external probe SNMP query in a dedicated event loop (sync wrapper)."""
    return asyncio.run(async_get_external_probe_data(host, community, snmp_port))


async def async_detect_external_probe_oids(
    host: str, community: str = "public", snmp_port: int = 161
) -> dict[str, str | None]:
    """Detect which external probe OIDs are available.

    This is intended to run during the hourly metadata poll. It identifies the
    specific OID variant that returns a sane, parseable value for each probe.

    Returns dict keys:
      - temp_1_oid, humidity_1_oid, temp_2_oid, humidity_2_oid
      - frequency_oid
    """

    candidates_by_key: dict[
        str, tuple[list[str], Callable[[str | None], float | None]]
    ] = {
        "temp_1_oid": (
            [
                f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.1.1",
                f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.1",
            ],
            _parse_external_temp_c,
        ),
        "humidity_1_oid": (
            [
                f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.1.1",
                f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.1",
            ],
            _parse_external_humidity_pct,
        ),
        "temp_2_oid": (
            [
                f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.2.1",
                f"{UIO_SENSOR_STATUS_TEMP_C_BASE}.2",
            ],
            _parse_external_temp_c,
        ),
        "humidity_2_oid": (
            [
                f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.2.1",
                f"{UIO_SENSOR_STATUS_HUMIDITY_BASE}.2",
            ],
            _parse_external_humidity_pct,
        ),
        "frequency_oid": (
            [SMARTUPS_OID_INPUT_FREQUENCY, UPS_MIB_OID_INPUT_FREQUENCY_LINE1],
            _parse_frequency_hz,
        ),
    }
    all_candidates = [
        oid for candidates, _parser in candidates_by_key.values() for oid in candidates
    ]
    value_map = await _fetch_snmp_value_map(
        host, community, all_candidates, snmp_port=snmp_port
    )
    detection: dict[str, str | None] = {}
    for key, (candidates, parser) in candidates_by_key.items():
        detection[key] = _select_first_usable_candidate_from_map(
            candidates, value_map, parser
        )

    _LOGGER.debug("SNMP external probe OID detection for %s: %s", host, detection)
    return detection


def detect_external_probe_oids_sync(
    host: str,
    community: str = "public",
    snmp_port: int = 161,
) -> dict[str, str | None]:
    """Run external probe detection in a dedicated event loop (sync wrapper)."""
    return asyncio.run(async_detect_external_probe_oids(host, community, snmp_port))


async def async_get_external_probe_data_detected(
    host: str,
    community: str,
    detection: dict[str, str | None],
    snmp_port: int = 161,
) -> dict[str, float | None]:
    """Fetch external probe values using a previously-detected OID map.

    Notes:
    - Temperature/humidity probes are only queried if their OID is present in
      the detection map.
    - Input frequency is queried if a frequency OID is present; this is useful
      for SMT devices where Modbus cannot provide line frequency.
    """
    oids: dict[str, str] = {}

    freq_oid = detection.get("frequency_oid")
    if isinstance(freq_oid, str) and freq_oid:
        oids["snmp_input_frequency"] = freq_oid

    temp_1_oid = detection.get("temp_1_oid")
    if isinstance(temp_1_oid, str) and temp_1_oid:
        oids["snmp_external_temp_1"] = temp_1_oid
    humidity_1_oid = detection.get("humidity_1_oid")
    if isinstance(humidity_1_oid, str) and humidity_1_oid:
        oids["snmp_external_humidity_1"] = humidity_1_oid
    temp_2_oid = detection.get("temp_2_oid")
    if isinstance(temp_2_oid, str) and temp_2_oid:
        oids["snmp_external_temp_2"] = temp_2_oid
    humidity_2_oid = detection.get("humidity_2_oid")
    if isinstance(humidity_2_oid, str) and humidity_2_oid:
        oids["snmp_external_humidity_2"] = humidity_2_oid

    if not oids:
        return {}

    value_map = await _fetch_snmp_value_map(
        host, community, list(oids.values()), snmp_port=snmp_port
    )

    parsed: dict[str, float | None] = {}
    for key, oid in oids.items():
        value = value_map.get(oid)
        if key == "snmp_input_frequency":
            parsed[key] = _parse_frequency_hz(value)
        elif key.startswith("snmp_external_temp"):
            parsed[key] = _parse_external_temp_c(value)
        else:
            parsed[key] = _parse_external_humidity_pct(value)

    return parsed


def get_external_probe_data_detected_sync(
    host: str,
    community: str,
    detection: dict[str, str | None],
    snmp_port: int = 161,
) -> dict[str, float | None]:
    """Run detected external probe SNMP query in a dedicated event loop (sync wrapper)."""
    return asyncio.run(
        async_get_external_probe_data_detected(host, community, detection, snmp_port)
    )


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
