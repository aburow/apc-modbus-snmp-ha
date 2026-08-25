# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Binary sensor definitions for APC UPS Modbus."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    APCModbusBinarySensorDescription,
    DOMAIN,
    KEY_COORDINATOR,
)
from .coordinator import APCModbusCoordinator
from .device_profiles import get_binary_sensor_descriptions
from .icons_unified import resolve_binary_sensor_icon
from .sensor_availability_unified import is_binary_sensor_enabled_by_default

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the APC UPS binary sensors."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][
        KEY_COORDINATOR
    ]

    binary_sensor_descriptions = get_binary_sensor_descriptions(
        coordinator.device_type, getattr(coordinator, "device_capabilities", {})
    )

    _LOGGER.debug(
        "Setting up %d binary sensors for device type %s",
        len(binary_sensor_descriptions),
        coordinator.device_type.value,
    )

    async_add_entities(
        APCModbusBinarySensor(coordinator, description, entry.entry_id)
        for description in binary_sensor_descriptions
    )


class APCModbusBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for APC UPS status bits."""

    has_entity_name = True

    def __init__(
        self,
        coordinator: APCModbusCoordinator,
        description: APCModbusBinarySensorDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
            sw_version=f"{coordinator.fw_version} ({coordinator.fw_date})"
            if coordinator.fw_version and coordinator.fw_date
            else coordinator.fw_version,
        )
        self._attr_icon = resolve_binary_sensor_icon(description.key)
        self._attr_entity_registry_enabled_default = (
            is_binary_sensor_enabled_by_default(
                description.key,
                coordinator.device_type.value,
            )
        )

    @property
    def is_on(self) -> bool | None:
        """Return the current state of the binary sensor."""
        value = self.coordinator.data.get(self.entity_description.register_key)
        if value is None:
            return None
        return bool(int(value) & (1 << self.entity_description.bit_index))
