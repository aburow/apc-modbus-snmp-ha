# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure APC Modbus schema classification helpers."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

DETECTION_VERSION = 4


class APCDeviceType(Enum):
    UPS = "ups"
    SMART_UPS = "smart_ups"
    SMT_UPS = "smt_ups"
    RACK_PDU = "rack_pdu"
    SMARTCONNECT_UPS = "smartconnect_ups"
    UNKNOWN = "unknown"


DEVICE_TYPE_LABELS = {
    APCDeviceType.UPS: "UPS",
    APCDeviceType.SMART_UPS: "Smart-UPS",
    APCDeviceType.SMT_UPS: "SMT/SMX UPS",
    APCDeviceType.RACK_PDU: "Rack PDU",
    APCDeviceType.SMARTCONNECT_UPS: "SmartConnect UPS",
    APCDeviceType.UNKNOWN: "Unknown APC device",
}


def device_type_label(device_type: APCDeviceType | None) -> str:
    """Return the stable user-facing label for a device family."""
    return DEVICE_TYPE_LABELS.get(
        device_type, DEVICE_TYPE_LABELS[APCDeviceType.UNKNOWN]
    )


class ProbeKind(Enum):
    RESPONSE = "response"
    MODBUS_EXCEPTION = "modbus_exception"
    SHORT_RESPONSE = "short_response"
    TRANSPORT_FAILURE = "transport_failure"


@dataclass(frozen=True)
class ProbeOutcome:
    """One probe result without collapsing protocol and transport evidence."""

    kind: ProbeKind
    registers: tuple[int, ...] = ()
    exception_code: int | None = None

    @property
    def completed(self) -> bool:
        return self.kind in (ProbeKind.RESPONSE, ProbeKind.MODBUS_EXCEPTION)

    @property
    def unsupported(self) -> bool:
        return self.kind == ProbeKind.MODBUS_EXCEPTION and self.exception_code == 2


@dataclass(frozen=True)
class SchemaProbe:
    """A read-only Modbus request used to identify an APC device family."""

    name: str
    address: int
    count: int


# Keep the wire-level classifier contract in one place.  Runtime detection and
# diagnostics deliberately perform these same read-only requests.
SCHEMA_PROBES = (
    SchemaProbe("rack_pdu_capabilities", 0x009E, 5),
    SchemaProbe("rack_pdu_measurements", 0x00CF, 6),
    SchemaProbe("legacy_ups_id", 0x0021, 1),
    SchemaProbe("smt_status", 0x0000, 23),
    SchemaProbe("smt_measurements", 0x0080, 26),
)


def is_concrete_device_type(device_type: APCDeviceType | None) -> bool:
    return device_type in (
        APCDeviceType.SMART_UPS,
        APCDeviceType.SMT_UPS,
        APCDeviceType.RACK_PDU,
        APCDeviceType.SMARTCONNECT_UPS,
    )


def should_probe_device_type(
    device_type: APCDeviceType | None,
    *,
    stored_detection_version: object,
    snmp_hint_device_type: APCDeviceType | None = None,
) -> bool:
    """Probe new/old entries or a current entry with a strong identity conflict."""
    if device_type in (None, APCDeviceType.UNKNOWN, APCDeviceType.UPS):
        return True
    if stored_detection_version != DETECTION_VERSION:
        return True
    return bool(
        is_concrete_device_type(snmp_hint_device_type)
        and snmp_hint_device_type != device_type
    )


def choose_device_type(
    *,
    stored_device_type: APCDeviceType | None,
    detected_device_type: APCDeviceType | None,
    snmp_hint_device_type: APCDeviceType | None = None,
) -> APCDeviceType | None:
    """Keep a stored concrete family unless Modbus gives a definitive result."""
    del snmp_hint_device_type
    if is_concrete_device_type(detected_device_type):
        return detected_device_type
    if is_concrete_device_type(stored_device_type):
        return stored_device_type
    return None


def _coherent_rack_pdu(capabilities: ProbeOutcome, measurements: ProbeOutcome) -> bool:
    if (
        capabilities.kind != ProbeKind.RESPONSE
        or measurements.kind != ProbeKind.RESPONSE
    ):
        return False
    if len(capabilities.registers) != 5 or len(measurements.registers) != 6:
        return False
    phases, metered_phases, banks, outlets, metered_outlets = capabilities.registers
    return (
        metered_phases <= phases
        and metered_outlets <= outlets
        and any((phases, banks, outlets))
        and 0 <= measurements.registers[5] <= 4
    )


def classify_device_type(probes: Mapping[str, ProbeOutcome]) -> APCDeviceType | None:
    """Classify only from definitive Modbus schema evidence."""
    capabilities = probes["rack_pdu_capabilities"]
    measurements = probes["rack_pdu_measurements"]
    legacy = probes["legacy_ups_id"]
    smt_status = probes["smt_status"]
    smt = probes["smt_measurements"]

    if _coherent_rack_pdu(capabilities, measurements):
        return APCDeviceType.RACK_PDU
    if smt.kind == ProbeKind.RESPONSE and legacy.unsupported:
        return APCDeviceType.SMT_UPS
    if legacy.kind == ProbeKind.RESPONSE and smt.unsupported:
        return APCDeviceType.SMART_UPS
    legacy_sentinel = (
        legacy.kind == ProbeKind.RESPONSE
        and len(legacy.registers) > 0
        and all(r == 0xFFFF for r in legacy.registers)
    )
    if (
        smt.kind == ProbeKind.RESPONSE
        and any(r != 0xFFFF for r in smt.registers)
        and smt_status.kind == ProbeKind.RESPONSE
        and any(r != 0 for r in smt_status.registers)
        and capabilities.unsupported
        and legacy_sentinel
    ):
        return APCDeviceType.SMARTCONNECT_UPS
    return None
