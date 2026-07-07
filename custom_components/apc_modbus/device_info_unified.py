# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow

"""Unified device-info resolver for external bridge consumers.

This module is dependency-free and safe to import outside Home Assistant.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

CONTRACT_VERSION = "1.0"

CANONICAL_DEVICE_INFO_KEYS = {
    "manufacturer",
    "model",
    "sw_version",
    "hw_version",
    "serial_number",
    "configuration_url",
}

_UNKNOWN_MARKERS = {
    "",
    "unknown",
    "unavailable",
    "none",
    "null",
    "n/a",
    "na",
}

_MANUFACTURER_KEYS = ("manufacturer", "vendor", "make")
_MODEL_KEYS = (
    "model",
    "hw_model",
    "device_model",
    "apc_model_smartups",
    "apc_model_rackpdu",
)
_SW_VERSION_KEYS = (
    "sw_version",
    "firmware_version",
    "firmware",
    "fw_version",
    "apc_fw_smartups",
    "apc_fw_rackpdu",
)
_HW_VERSION_KEYS = (
    "hw_version",
    "hardware_version",
    "firmware_date",
    "fw_date",
    "apc_fw_date_smartups",
    "apc_fw_date_rackpdu",
)
_SERIAL_KEYS = ("serial_number", "serial", "apc_serial_smartups", "apc_serial_rackpdu")
_CONFIG_URL_KEYS = (
    "configuration_url",
    "config_url",
    "web_url",
    "management_url",
    "url",
)
_HOST_KEYS = ("host", "ip", "ip_address", "address")


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
    elif isinstance(value, (int, float, bool)):
        normalized = str(value).strip()
    else:
        return None
    if normalized.lower() in _UNKNOWN_MARKERS:
        return None
    return normalized


def _first_non_empty(values: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        normalized = _normalize(values.get(key))
        if normalized:
            return normalized
    return None


def _is_full_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resolve_configuration_url(values: dict[str, Any]) -> str | None:
    direct = _first_non_empty(values, _CONFIG_URL_KEYS)
    if direct and _is_full_http_url(direct):
        return direct

    host = _first_non_empty(values, _HOST_KEYS)
    if not host:
        return None

    candidate = f"http://{host}"
    return candidate if _is_full_http_url(candidate) else None


def resolve_device_info(values: dict[str, Any], source: str) -> dict[str, str]:
    """Return canonical device info fields for MQTT discovery device block."""
    if not isinstance(values, dict):
        return {}

    source_normalized = _normalize(source) or ""

    resolved: dict[str, str] = {}
    manufacturer = _first_non_empty(values, _MANUFACTURER_KEYS)
    if not manufacturer and "apc" in source_normalized.lower():
        manufacturer = "APC"

    model = _first_non_empty(values, _MODEL_KEYS)
    sw_version = _first_non_empty(values, _SW_VERSION_KEYS)
    hw_version = _first_non_empty(values, _HW_VERSION_KEYS)
    serial_number = _first_non_empty(values, _SERIAL_KEYS)
    configuration_url = _resolve_configuration_url(values)

    for key, value in (
        ("manufacturer", manufacturer),
        ("model", model),
        ("sw_version", sw_version),
        ("hw_version", hw_version),
        ("serial_number", serial_number),
        ("configuration_url", configuration_url),
    ):
        if value:
            resolved[key] = value

    return {
        key: value
        for key, value in resolved.items()
        if key in CANONICAL_DEVICE_INFO_KEYS
    }
