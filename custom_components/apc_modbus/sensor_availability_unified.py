# SPDX-FileCopyrightText: 2026 github.com/aburow
# SPDX-License-Identifier: GPL-3.0-only

"""Unified default sensor availability profiles (dependency-free).

This module intentionally has no Home Assistant imports so it can be shared
across projects and external tooling.
"""

from __future__ import annotations

import re


UPS_DEVICE_FAMILIES = ("smart_ups", "smt_ups", "ups", "unknown")
RACK_PDU_DEVICE_FAMILIES = ("rack_pdu",)

STANDARD_ENABLED_CANONICAL_KEYS: tuple[str, ...] = (
    "runtime_remaining",
    "battery_state_of_charge",
    "input_voltage",
    "output_voltage",
    "output_load_percent",
    "output_frequency",
    "online_state",
    "on_battery_state",
    "on_bypass_state",
    "overload_state",
)

STANDARD_ENABLED_CANONICAL_SET = set(STANDARD_ENABLED_CANONICAL_KEYS)

RACK_PDU_ENABLED_CANONICAL_KEYS: tuple[str, ...] = (
    "device_real_power",
    "device_apparent_power",
    "device_power_factor",
    "device_energy",
    "phase_l1_current",
    "phase_l1_voltage",
)

RACK_PDU_ENABLED_CANONICAL_SET = set(RACK_PDU_ENABLED_CANONICAL_KEYS)

SENSOR_CANONICAL_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("runtime", "seconds_on_battery"), "runtime_remaining"),
    (
        ("state_of_charge", "battery_charge", "battery_capacity"),
        "battery_state_of_charge",
    ),
    (("input_voltage", "utility_voltage"), "input_voltage"),
    (
        ("output_voltage", "actual_output_voltage", "nominal_output_voltage"),
        "output_voltage",
    ),
    (("output_load_percent", "load_percent", "output_load"), "output_load_percent"),
    (("output_frequency",), "output_frequency"),
    # Legacy Smart-UPS does not expose output frequency cleanly in this map.
    (("input_frequency",), "output_frequency"),
)

BINARY_CANONICAL_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ups_online", "online", "ac_power", "mains"), "online_state"),
    (("ups_on_battery", "on_battery"), "on_battery_state"),
    (("ups_on_bypass", "on_bypass", "bypass"), "on_bypass_state"),
    (("ups_overload", "overload"), "overload_state"),
)

RACK_PDU_SENSOR_CANONICAL_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("device_real_power",), "device_real_power"),
    (("device_apparent_power",), "device_apparent_power"),
    (("device_power_factor",), "device_power_factor"),
    (("device_energy",), "device_energy"),
    (("phase_l1_current",), "phase_l1_current"),
    (("phase_l1_voltage",), "phase_l1_voltage"),
)

NON_PRIMARY_PHASE_SUFFIX_RE = re.compile(r"(?:^|_)(?:l|phase)([2-9]\d*)$")


def _is_non_primary_phase_metric(local_key: str) -> bool:
    match = NON_PRIMARY_PHASE_SUFFIX_RE.search(local_key.lower())
    return bool(match and int(match.group(1)) >= 2)


def _match_pattern_key(
    local_key: str, patterns: tuple[tuple[tuple[str, ...], str], ...]
) -> str | None:
    key_lower = local_key.lower()
    for fragments, canonical_key in patterns:
        if any(fragment in key_lower for fragment in fragments):
            return canonical_key
    return None


def resolve_sensor_canonical_key(local_key: str) -> str | None:
    """Resolve a local sensor key to its canonical sensor key."""
    return _match_pattern_key(local_key, SENSOR_CANONICAL_PATTERNS)


def resolve_binary_canonical_key(local_key: str) -> str | None:
    """Resolve a local binary sensor key to its canonical binary key."""
    return _match_pattern_key(local_key, BINARY_CANONICAL_PATTERNS)


def resolve_rack_pdu_sensor_canonical_key(local_key: str) -> str | None:
    """Resolve a local rack-pdu sensor key to its canonical sensor key."""
    return _match_pattern_key(local_key, RACK_PDU_SENSOR_CANONICAL_PATTERNS)


def is_sensor_enabled_by_default(local_key: str, device_family: str) -> bool:
    """Return whether a sensor should be entity-registry enabled by default."""
    if local_key.lower().startswith("snmp_external_"):
        # External SNMP probes should be visible immediately when detected.
        return True

    if device_family in RACK_PDU_DEVICE_FAMILIES:
        canonical_key = resolve_rack_pdu_sensor_canonical_key(local_key)
        return canonical_key in RACK_PDU_ENABLED_CANONICAL_SET

    if device_family not in UPS_DEVICE_FAMILIES:
        return True

    if _is_non_primary_phase_metric(local_key):
        return False

    canonical_key = resolve_sensor_canonical_key(local_key)
    return canonical_key in STANDARD_ENABLED_CANONICAL_SET


def is_binary_sensor_enabled_by_default(local_key: str, device_family: str) -> bool:
    """Return whether a binary sensor should be entity-registry enabled by default."""
    if device_family in RACK_PDU_DEVICE_FAMILIES:
        return False

    if device_family not in UPS_DEVICE_FAMILIES:
        return True
    canonical_key = resolve_binary_canonical_key(local_key)
    return canonical_key in STANDARD_ENABLED_CANONICAL_SET


def entity_enabled_default(local_entity_key: str) -> bool:
    """External contract API: default-enabled state without device-family context."""
    if not isinstance(local_entity_key, str):
        return True

    if resolve_rack_pdu_sensor_canonical_key(local_entity_key) is not None:
        return is_sensor_enabled_by_default(local_entity_key, "rack_pdu")

    if resolve_sensor_canonical_key(local_entity_key) is not None:
        return is_sensor_enabled_by_default(local_entity_key, "unknown")
    return is_binary_sensor_enabled_by_default(local_entity_key, "unknown")
