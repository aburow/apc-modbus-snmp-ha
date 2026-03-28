# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Device type definitions for APC devices."""

from enum import Enum


class APCDeviceType(Enum):
    """Enumeration of supported APC device types."""

    UPS = "ups"
    SMART_UPS = "smart_ups"
    SMT_UPS = "smt_ups"
    RACK_PDU = "rack_pdu"
    UNKNOWN = "unknown"


def classify_smart_ups_family(
    *,
    legacy_probe_ok: bool,
    smt_status_ok: bool,
    smt_measurements_ok: bool,
) -> APCDeviceType | None:
    """Classify a Smart-UPS family from distinguishing Modbus probe results.

    Returns:
        `SMT_UPS` when SMT-specific blocks succeed and the legacy-only probe fails.
        `SMART_UPS` when the legacy-only probe succeeds and SMT probes fail.
        `None` when the result is ambiguous and the caller should keep the current type.
    """
    smt_ok = smt_status_ok and smt_measurements_ok

    if smt_ok and not legacy_probe_ok:
        return APCDeviceType.SMT_UPS

    if legacy_probe_ok and not smt_ok:
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
        `RACK_PDU` when PDU-specific blocks succeed.
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
