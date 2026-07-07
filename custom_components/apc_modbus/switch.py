# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Switch platform for APC UPS runtime controls."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_KEEP_CONNECTION_OPEN, DOMAIN, KEY_COORDINATOR
from .coordinator import APCModbusCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up APC Modbus switches for a config entry."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][
        KEY_COORDINATOR
    ]
    async_add_entities(
        [APCModbusKeepConnectionOpenSwitch(coordinator, entry)],
    )


class APCModbusKeepConnectionOpenSwitch(
    CoordinatorEntity[APCModbusCoordinator], SwitchEntity
):
    """Toggle persistent Modbus TCP session behavior."""

    has_entity_name = True
    _attr_name = "Keep Connection Open"
    _attr_icon = "mdi:ethernet-cable"

    def __init__(self, coordinator: APCModbusCoordinator, entry: ConfigEntry) -> None:
        """Initialize keep-connection-open switch."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_keep_connection_open"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    @property
    def is_on(self) -> bool:
        """Return current keep-connection-open state."""
        return self.coordinator.keep_connection_open_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable open-session mode and persist to config entry."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable open-session mode and persist to config entry."""
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        """Persist config and apply runtime state."""
        if self._entry.data.get(CONF_KEEP_CONNECTION_OPEN, False) != enabled:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_KEEP_CONNECTION_OPEN: enabled},
            )
        await self.coordinator.async_set_keep_connection_open(enabled)
        self.async_write_ha_state()
