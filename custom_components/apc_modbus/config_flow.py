# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Config flow for the APC UPS Modbus integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL

from .const import (
    CONF_DEVICE_NAME,
    CONF_KEEP_CONNECTION_OPEN,
    CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_WRITE_COMMUNITY,
    CONF_SNMP_PORT,
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


class APCModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle APC UPS Modbus config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Handle the initial config flow step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        return self.async_create_entry(
            title=user_input.get(CONF_DEVICE_NAME, user_input[CONF_HOST]),
            data={**user_input},
        )
