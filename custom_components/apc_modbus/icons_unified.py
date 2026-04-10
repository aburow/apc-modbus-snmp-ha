# SPDX-FileCopyrightText: 2026 github.com/aburow
# SPDX-License-Identifier: GPL-3.0-only

"""
Unified icon mapping for UPS/PDU metrics.

Merges icon definitions from cyberpower-modbus-ha, apc-modbus-ha, and ups-snmp-ha
into a single, framework-independent module with no homeassistant dependencies.

This is the canonical reference implementation suitable for:
- Embedding in ups_unified_mqtt icon resolver
- Standardizing across all three HACS projects
- Using in standalone tools and external integrations
"""

from __future__ import annotations


# ============================================================================
# SENSOR ICONS - Metrics and measurements
# ============================================================================

SENSOR_ICON_MAPPING: tuple[tuple[tuple[str, ...], str], ...] = (
    # Temperature sensors (specific before general)
    (("over_temperature",), "mdi:thermometer-alert"),
    (("temperature", "temp"), "mdi:thermometer"),
    # Humidity
    (("humidity",), "mdi:water-percent"),
    # Battery - Specific patterns (must come before voltage to match battery_voltage)
    (("state_of_charge", "battery_capacity", "battery_charge"), "mdi:battery"),
    (("battery_voltage",), "mdi:battery"),
    # Battery - General fallback
    (("battery",), "mdi:battery-medium"),
    # Electrical - Voltage (after battery patterns)
    (("voltage", "volt", "transfer_point"), "mdi:sine-wave"),
    # Electrical - Current
    (("current", "amperage", "amps"), "mdi:current-ac"),
    # Electrical - Power (specific before general)
    (("apparent_power",), "mdi:flash-outline"),
    (("reactive_power",), "mdi:flash"),
    (("real_power",), "mdi:flash"),
    (("active_power",), "mdi:flash"),
    (("power",), "mdi:flash"),
    (("power_factor",), "mdi:angle-acute"),
    # Electrical - Energy
    (("energy",), "mdi:meter-electric"),
    # Frequency
    (("frequency",), "mdi:sine-wave"),
    # Time-based (specific before general)
    (("runtime_low",), "mdi:timer-alert"),
    (("runtime", "seconds_on_battery"), "mdi:timer-outline"),
    (("delay",), "mdi:timer-outline"),
    (("duration",), "mdi:timer-outline"),
    # State/condition sensors (specific before general load)
    (("buzzer_muted",), "mdi:volume-off"),
    (("input_fail", "bypass_fail", "general_error"), "mdi:alert-circle"),
    (("inverter_off",), "mdi:power"),
    (("load_on_source",), "mdi:power-plug"),
    (("no_output", "output_off", "output_disabled"), "mdi:power-plug-off"),
    (("output_shorted",), "mdi:flash-alert"),
    (("overload", "bypass_overload"), "mdi:car-brake-alert"),
    (("bypass",), "mdi:transit-detour"),
    # Load and gauge metrics (after more specific state patterns)
    (("load",), "mdi:gauge"),
    (("line_count", "phase_count"), "mdi:transmission-tower"),
    # Status and state indicators (specific before general)
    (("alarm", "alarms"), "mdi:alert-circle-outline"),
    (("fault",), "mdi:alert-circle-outline"),
    (("status", "state", "result", "source"), "mdi:information-outline"),
)

SENSOR_DEFAULT_ICON = "mdi:gauge"


# ============================================================================
# BINARY SENSOR ICONS - On/Off states and conditions
# ============================================================================

BINARY_SENSOR_ICON_MAPPING: tuple[tuple[tuple[str, ...], str], ...] = (
    # Faults and errors
    (("fault", "fail", "problem", "error"), "mdi:alert-circle"),
    # Overload conditions
    (("overload",), "mdi:car-brake-alert"),
    # Battery alerts and status
    (
        ("battery_eod", "battery_not_present", "battery_volt_low", "battery_low"),
        "mdi:battery-alert",
    ),
    (("battery_charging",), "mdi:battery-charging"),
    (("battery_fully_charged",), "mdi:battery-check"),
    (("battery_discharging",), "mdi:battery-arrow-down"),
    (("battery",), "mdi:battery"),
    # Bypass mode
    (("bypass", "on_bypass"), "mdi:transit-detour"),
    # Power and online status
    (("online", "load_on_source", "ac_power", "mains"), "mdi:power-plug"),
    (("no_output", "output_off", "output_disabled"), "mdi:power-plug-off"),
    # Output conditions
    (("output_shorted",), "mdi:flash-alert"),
    (("inverter_off",), "mdi:power"),
    # Audio alerts
    (("buzzer_muted",), "mdi:volume-off"),
)

BINARY_SENSOR_DEFAULT_ICON = "mdi:help-circle-outline"


# ============================================================================
# Resolution functions
# ============================================================================


def _match_icon(
    register_key: str,
    mapping: tuple[tuple[tuple[str, ...], str], ...],
    default_icon: str,
) -> str:
    """Resolve icon by matching key against pattern tuples.

    Args:
        register_key: The metric/register key to match (e.g. "battery_capacity")
        mapping: Tuple of (patterns, icon) pairs
        default_icon: Icon to return if no patterns match

    Returns:
        Material Design Icon string (e.g. "mdi:battery")
    """
    key_lower = register_key.lower()
    for patterns, icon in mapping:
        if any(pattern in key_lower for pattern in patterns):
            return icon
    return default_icon


def resolve_sensor_icon(register_key: str) -> str:
    """Resolve a deterministic mdi icon for a sensor/metric key.

    Args:
        register_key: The metric/register key (e.g. "battery_capacity")

    Returns:
        Material Design Icon string like "mdi:battery"

    Examples:
        >>> resolve_sensor_icon("battery_capacity")
        "mdi:battery"
        >>> resolve_sensor_icon("output_voltage")
        "mdi:sine-wave"
        >>> resolve_sensor_icon("runtime_remaining")
        "mdi:timer-outline"
    """
    return _match_icon(register_key, SENSOR_ICON_MAPPING, SENSOR_DEFAULT_ICON)


def resolve_binary_sensor_icon(register_key: str) -> str:
    """Resolve a deterministic mdi icon for a binary sensor key.

    Args:
        register_key: The binary sensor/condition key (e.g. "battery_low")

    Returns:
        Material Design Icon string like "mdi:battery-alert"

    Examples:
        >>> resolve_binary_sensor_icon("battery_low")
        "mdi:battery-alert"
        >>> resolve_binary_sensor_icon("output_overload")
        "mdi:car-brake-alert"
        >>> resolve_binary_sensor_icon("online")
        "mdi:power-plug"
    """
    return _match_icon(
        register_key, BINARY_SENSOR_ICON_MAPPING, BINARY_SENSOR_DEFAULT_ICON
    )
