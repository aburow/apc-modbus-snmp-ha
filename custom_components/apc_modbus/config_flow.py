# SPDX-License-Identifier: GPL-3.0
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
    CONF_DEVICE_TYPE,
    CONF_DEBUG_DUMP,
    CONF_SNMP_COMMUNITY,
    CONF_UNIT,
    DEFAULT_DEBUG_DUMP,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_UNIT,
    DOMAIN,
)
from .device_types import APCDeviceType


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SNMP_COMMUNITY, default=DEFAULT_SNMP_COMMUNITY): str,
        vol.Required(CONF_DEVICE_TYPE): vol.In(
            {
                APCDeviceType.SMART_UPS.value: "Smart-UPS (legacy, excl. SMT/SMX/SRT)",
                APCDeviceType.SMT_UPS.value: "Smart-UPS SMT / SMX / SRT",
                APCDeviceType.RACK_PDU.value: "NetShelter Rack PDU",
            }
        ),
        vol.Optional(CONF_DEVICE_NAME, default=DEFAULT_NAME): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        vol.Optional(CONF_UNIT, default=DEFAULT_UNIT): int,
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

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return APCModbusOptionsFlowHandler(config_entry)


class APCModbusOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle APC UPS Modbus options."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_DEBUG_DUMP,
                        default=self._entry.options.get(
                            CONF_DEBUG_DUMP, DEFAULT_DEBUG_DUMP
                        ),
                    ): bool,
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        return self.async_create_entry(title="", data=user_input)
