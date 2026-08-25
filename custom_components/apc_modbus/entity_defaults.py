# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow

"""Helpers for applying entity-registry monitor defaults."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .modbus_commands import COMMANDS, OUTLET_ACTION_BITS, OUTLET_TARGET_BITS
from .sensor_availability_unified import (
    is_binary_sensor_enabled_by_default,
    is_sensor_enabled_by_default,
)
from .snmp_commands import LEGACY_SNMP_COMMANDS

WRITE_ENTITY_KEYS = (
    set(COMMANDS)
    | set(LEGACY_SNMP_COMMANDS)
    | {
        f"{action}_{target}"
        for action in OUTLET_ACTION_BITS
        for target in OUTLET_TARGET_BITS
    }
)


async def async_reset_entry_monitors_to_defaults(
    hass: HomeAssistant,
    *,
    entry_id: str,
    device_family: str,
) -> tuple[int, int, int]:
    """Reset monitor defaults and disable write controls.

    Returns tuple: (enabled_count, disabled_count, unchanged_count).
    """
    ent_reg = er.async_get(hass)
    unique_id_prefix = f"{DOMAIN}_{entry_id}_"
    enabled_count = 0
    disabled_count = 0
    unchanged_count = 0

    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry_id):
        unique_id = entity_entry.unique_id or ""
        if not unique_id.startswith(unique_id_prefix):
            continue

        local_key = unique_id[len(unique_id_prefix) :]
        if entity_entry.domain == "sensor":
            should_enable = is_sensor_enabled_by_default(local_key, device_family)
        elif entity_entry.domain == "binary_sensor":
            should_enable = is_binary_sensor_enabled_by_default(
                local_key, device_family
            )
        elif entity_entry.domain in {"button", "switch"} and (
            local_key in WRITE_ENTITY_KEYS or local_key.startswith("write_")
        ):
            should_enable = False
        else:
            continue

        target_disabled_by = (
            None if should_enable else er.RegistryEntryDisabler.INTEGRATION
        )
        if entity_entry.disabled_by == target_disabled_by:
            unchanged_count += 1
            continue

        ent_reg.async_update_entity(
            entity_entry.entity_id,
            disabled_by=target_disabled_by,
        )
        if should_enable:
            enabled_count += 1
        else:
            disabled_count += 1

    return enabled_count, disabled_count, unchanged_count
