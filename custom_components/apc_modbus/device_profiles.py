# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete read-only profiles for supported APC Modbus device families."""

from dataclasses import dataclass
from typing import Any

from .device_types import APCDeviceType

try:
    from .device_types import SCHEMA_PROBES, SchemaProbe
except ImportError:  # Lightweight entity-platform test stubs omit probe types.
    SCHEMA_PROBES = ()
    SchemaProbe = object


@dataclass(frozen=True)
class DeviceProfile:
    """Family-specific data used by setup and entity selection."""

    device_type: APCDeviceType
    register_map: str
    sensor_descriptions: str
    binary_sensor_descriptions: str
    aliases: tuple[str, ...]
    dynamic_capabilities: bool = False
    probes: tuple[SchemaProbe, ...] = SCHEMA_PROBES


SMART_UPS_PROFILE = DeviceProfile(
    APCDeviceType.SMART_UPS,
    "smart_ups",
    "SENSOR_DESCRIPTIONS",
    "BINARY_SENSOR_DESCRIPTIONS",
    ("ups",),
)
SMT_UPS_PROFILE = DeviceProfile(
    APCDeviceType.SMT_UPS,
    "smt_ups",
    "SENSOR_DESCRIPTIONS",
    "BINARY_SENSOR_DESCRIPTIONS",
    ("smx_ups", "srt_ups"),
)
SMARTCONNECT_UPS_PROFILE = DeviceProfile(
    APCDeviceType.SMARTCONNECT_UPS,
    "smt_ups",
    "SMARTCONNECT_SENSOR_DESCRIPTIONS",
    "BINARY_SENSOR_DESCRIPTIONS",
    (),
)
RACK_PDU_PROFILE = DeviceProfile(
    APCDeviceType.RACK_PDU,
    "rack_pdu",
    "get_sensor_descriptions",
    "get_binary_sensor_descriptions",
    (),
    dynamic_capabilities=True,
)

DEVICE_PROFILES = {
    profile.device_type: profile
    for profile in (
        SMART_UPS_PROFILE,
        SMT_UPS_PROFILE,
        SMARTCONNECT_UPS_PROFILE,
        RACK_PDU_PROFILE,
    )
}


def get_device_profile(device_type: APCDeviceType) -> DeviceProfile:
    """Return a concrete profile, retaining the established Smart-UPS fallback."""
    return DEVICE_PROFILES.get(device_type, SMART_UPS_PROFILE)


def get_sensor_descriptions(
    device_type: APCDeviceType, capabilities: dict[str, int]
) -> list[Any]:
    """Return the profile's monitor sensor descriptions."""
    profile = get_device_profile(device_type)
    if profile.register_map == "smart_ups":
        from .const import SENSOR_DESCRIPTIONS

        return list(SENSOR_DESCRIPTIONS)
    if profile.register_map == "smt_ups":
        from . import registers_smt_ups

        return list(getattr(registers_smt_ups, profile.sensor_descriptions))

    from . import registers_rack_pdu

    return registers_rack_pdu.get_sensor_descriptions(capabilities)


def get_binary_sensor_descriptions(
    device_type: APCDeviceType, capabilities: dict[str, int]
) -> list[Any]:
    """Return the profile's monitor binary-sensor descriptions."""
    profile = get_device_profile(device_type)
    if profile.register_map == "smart_ups":
        from .const import BINARY_SENSOR_DESCRIPTIONS

        return list(BINARY_SENSOR_DESCRIPTIONS)
    if profile.register_map == "smt_ups":
        from . import registers_smt_ups

        return list(registers_smt_ups.BINARY_SENSOR_DESCRIPTIONS)

    from . import registers_rack_pdu

    return registers_rack_pdu.get_binary_sensor_descriptions(capabilities)
