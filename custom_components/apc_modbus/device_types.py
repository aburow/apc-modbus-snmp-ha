# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Device type definitions for APC devices."""

from enum import Enum

DETECTION_VERSION = 1


class APCDeviceType(Enum):
    """Enumeration of supported APC device types."""

    UPS = "ups"
    SMART_UPS = "smart_ups"
    SMT_UPS = "smt_ups"
    RACK_PDU = "rack_pdu"
    UNKNOWN = "unknown"


def is_concrete_device_type(device_type: APCDeviceType | None) -> bool:
    """Return True when the device type is a concrete supported family."""
    return device_type in (
        APCDeviceType.SMART_UPS,
        APCDeviceType.SMT_UPS,
        APCDeviceType.RACK_PDU,
    )


def should_probe_device_type(
    device_type: APCDeviceType | None,
    *,
    stored_detection_version: int | None,
    snmp_hint_device_type: APCDeviceType | None = None,
) -> bool:
    """Return True when startup should perform Modbus family probes.

    Detection is performed on first add or when strong SNMP identity metadata
    conflicts with the stored concrete type. Concrete stored families are not
    automatically re-probed just because the detection algorithm version
    changes; use manual re-detect for that path.
    """
    if device_type in (None, APCDeviceType.UNKNOWN, APCDeviceType.UPS):
        return True

    _ = stored_detection_version

    return bool(
        is_concrete_device_type(snmp_hint_device_type)
        and snmp_hint_device_type != device_type
    )


def choose_device_type(
    *,
    stored_device_type: APCDeviceType | None,
    detected_device_type: APCDeviceType | None,
    snmp_hint_device_type: APCDeviceType | None = None,
) -> APCDeviceType:
    """Resolve the best concrete device type from stored, probed, and SNMP hints."""
    if is_concrete_device_type(detected_device_type):
        return detected_device_type

    if is_concrete_device_type(stored_device_type):
        return stored_device_type

    if is_concrete_device_type(snmp_hint_device_type):
        return snmp_hint_device_type

    return APCDeviceType.SMART_UPS


def classify_smart_ups_family(
    *,
    legacy_probe_ok: bool,
    smt_status_ok: bool,
    smt_measurements_ok: bool,
) -> APCDeviceType | None:
    """Classify a Smart-UPS family from distinguishing Modbus probe results.

    Notes:
        `0x0080` (SMT measurements) and `0x0021` (legacy UPS ID) are the
        strongest discriminators in mixed hardware/firmware environments.
        `0x0000` is probed for extra signal but can succeed across families.

    Returns:
        `SMT_UPS` when SMT measurement probe succeeds and legacy ID probe fails.
        `SMART_UPS` when legacy ID probe succeeds and SMT measurement probe fails.
        `None` when both (or neither) discriminators succeed.
    """
    _ = smt_status_ok  # Kept in signature for compatibility and future weighting.

    if smt_measurements_ok and not legacy_probe_ok:
        return APCDeviceType.SMT_UPS

    if legacy_probe_ok and not smt_measurements_ok:
        return APCDeviceType.SMART_UPS

    return None


def classify_device_type(
    *,
    rack_pdu_capabilities_ok: bool,
    rack_pdu_measurements_ok: bool,
    legacy_probe_ok: bool,
    smt_status_ok: bool,
    smt_measurements_ok: bool,
) -> APCDeviceType | None:
    """Classify APC device type from Modbus probe results.

    Returns:
        `RACK_PDU` when PDU-specific blocks strongly identify Rack PDU behavior.
        `SMT_UPS` or `SMART_UPS` when UPS-family probes clearly identify the device.
        `None` when results are ambiguous.
    """
    rack_pdu_ok = rack_pdu_capabilities_ok and rack_pdu_measurements_ok

    if rack_pdu_ok:
        return APCDeviceType.RACK_PDU

    return classify_smart_ups_family(
        legacy_probe_ok=legacy_probe_ok,
        smt_status_ok=smt_status_ok,
        smt_measurements_ok=smt_measurements_ok,
    )
