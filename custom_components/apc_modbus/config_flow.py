# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Config flow for the APC UPS Modbus integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import callback

from .const import (
    CONF_DETECTION_VERSION,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TYPE,
    CONF_KEEP_CONNECTION_OPEN,
    CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_WRITE_COMMUNITY,
    CONF_SNMP_PORT,
    CONF_TRANSPORT_MODE,
    CONF_UNIT,
    DEFAULT_KEEP_CONNECTION_OPEN,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_SNMP_WRITE_COMMUNITY,
    DEFAULT_SNMP_PORT,
    DEFAULT_UNIT,
    DOMAIN,
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SNMP_COMMUNITY, default=DEFAULT_SNMP_COMMUNITY): str,
        vol.Optional(
            CONF_SNMP_WRITE_COMMUNITY, default=DEFAULT_SNMP_WRITE_COMMUNITY
        ): str,
        vol.Optional(CONF_SNMP_PORT, default=DEFAULT_SNMP_PORT): int,
        vol.Optional(CONF_DEVICE_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_UNIT, default=DEFAULT_UNIT): int,
        vol.Optional(
            CONF_KEEP_CONNECTION_OPEN, default=DEFAULT_KEEP_CONNECTION_OPEN
        ): bool,
        vol.Optional(CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS, default=0): vol.All(
            int, vol.Range(min=0)
        ),
    }
)


def _schema_with_defaults(data: dict[str, Any]) -> vol.Schema:
    """Build the configuration schema pre-filled from an existing entry."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=data.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_SNMP_COMMUNITY,
                default=data.get(CONF_SNMP_COMMUNITY, DEFAULT_SNMP_COMMUNITY),
            ): str,
            vol.Optional(
                CONF_SNMP_WRITE_COMMUNITY,
                default=data.get(
                    CONF_SNMP_WRITE_COMMUNITY, DEFAULT_SNMP_WRITE_COMMUNITY
                ),
            ): str,
            vol.Optional(
                CONF_SNMP_PORT,
                default=data.get(CONF_SNMP_PORT, DEFAULT_SNMP_PORT),
            ): int,
            vol.Optional(
                CONF_DEVICE_NAME,
                default=data.get(CONF_DEVICE_NAME, DEFAULT_NAME),
            ): str,
            vol.Optional(CONF_PORT, default=data.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): int,
            vol.Optional(CONF_UNIT, default=data.get(CONF_UNIT, DEFAULT_UNIT)): int,
            vol.Optional(
                CONF_KEEP_CONNECTION_OPEN,
                default=data.get(
                    CONF_KEEP_CONNECTION_OPEN, DEFAULT_KEEP_CONNECTION_OPEN
                ),
            ): bool,
            vol.Optional(
                CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS,
                default=data.get(CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS, 0),
            ): vol.All(int, vol.Range(min=0)),
        }
    )


class APCModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle APC UPS Modbus config flow."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> APCModbusOptionsFlow:
        """Return the options flow for an existing entry."""
        return APCModbusOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial config flow step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        return self.async_create_entry(
            title=user_input.get(CONF_DEVICE_NAME, user_input[CONF_HOST]),
            data={**user_input},
        )


class APCModbusOptionsFlow(config_entries.OptionsFlow):
    """Edit connection and monitoring settings without re-adding a device."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Store the entry being updated."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Handle the integration Configure action."""
        if user_input is None:
            return self.async_show_form(
                step_id="init",
                data_schema=_schema_with_defaults(dict(self.config_entry.data)),
            )

        updated_data = {**self.config_entry.data, **user_input}
        endpoint_changed = any(
            user_input[key] != self.config_entry.data.get(key)
            for key in (CONF_HOST, CONF_PORT, CONF_UNIT)
        )
        if endpoint_changed:
            # A different endpoint/unit needs fresh, read-only schema detection.
            updated_data.pop(CONF_DEVICE_TYPE, None)
            updated_data.pop(CONF_DETECTION_VERSION, None)
            updated_data.pop(CONF_TRANSPORT_MODE, None)

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=updated_data,
            title=user_input.get(CONF_DEVICE_NAME, user_input[CONF_HOST]),
        )
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        return self.async_create_entry(title="", data={})
