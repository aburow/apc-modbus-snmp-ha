# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Helpers for optional SNMP external probe entity availability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

OPTIONAL_SNMP_EXTERNAL_KEYS = frozenset(
    {
        "snmp_external_temp_1",
        "snmp_external_humidity_1",
        "snmp_external_temp_2",
        "snmp_external_humidity_2",
    }
)

EXTERNAL_PROBE_KEY_TO_DETECTION_OID = {
    "snmp_external_temp_1": "temp_1_oid",
    "snmp_external_humidity_1": "humidity_1_oid",
    "snmp_external_temp_2": "temp_2_oid",
    "snmp_external_humidity_2": "humidity_2_oid",
}


def is_external_probe_entity_available(
    key: str,
    data: Mapping[str, Any],
    detection: Mapping[str, Any] | None,
) -> bool:
    """Return whether an optional SNMP external probe entity should exist."""
    if key not in OPTIONAL_SNMP_EXTERNAL_KEYS:
        return True

    if data.get(key) is not None:
        return True

    detection_key = EXTERNAL_PROBE_KEY_TO_DETECTION_OID.get(key)
    if detection_key is None or not isinstance(detection, Mapping):
        return False
    return bool(detection.get(detection_key))


def filter_available_external_probe_keys(
    keys: set[str],
    data: Mapping[str, Any],
    detection: Mapping[str, Any] | None,
) -> set[str]:
    """Filter optional SNMP external probe keys by value or detected OID."""
    return {
        key for key in keys if is_external_probe_entity_available(key, data, detection)
    }
