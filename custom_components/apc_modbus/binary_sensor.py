# SPDX-License-Identifier: GPL-3.0
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
from .device_types import APCDeviceType

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the APC UPS binary sensors."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][KEY_COORDINATOR]

    # Get device-type-specific binary sensor descriptions
    if coordinator.device_type == APCDeviceType.SMART_UPS:
        # Smart-UPS uses static binary sensor descriptions from const
        from .const import BINARY_SENSOR_DESCRIPTIONS
        binary_sensor_descriptions = BINARY_SENSOR_DESCRIPTIONS
    elif coordinator.device_type == APCDeviceType.RACK_PDU:
        # Rack PDU uses dynamic binary sensor descriptions based on capabilities
        from . import registers_rack_pdu
        binary_sensor_descriptions = registers_rack_pdu.get_binary_sensor_descriptions(coordinator.device_capabilities)
    else:
        # Unknown type defaults to Smart-UPS binary sensor descriptions
        from .const import BINARY_SENSOR_DESCRIPTIONS
        binary_sensor_descriptions = BINARY_SENSOR_DESCRIPTIONS

    _LOGGER.debug("Setting up %d binary sensors for device type %s", len(binary_sensor_descriptions), coordinator.device_type.value)

    async_add_entities(
        APCModbusBinarySensor(coordinator, description, entry.entry_id) for description in binary_sensor_descriptions
    )


class APCModbusBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for APC UPS status bits."""

    has_entity_name = True

    def __init__(self, coordinator: APCModbusCoordinator, description: APCModbusBinarySensorDescription, entry_id: str) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.hw_model or "Smart-UPS",
            serial_number=coordinator.serial_number,
            sw_version=f"{coordinator.fw_version} ({coordinator.fw_date})" if coordinator.fw_version and coordinator.fw_date else coordinator.fw_version,
        )

    @property
    def is_on(self) -> bool | None:
        """Return the current state of the binary sensor."""
        value = self.coordinator.data.get(self.entity_description.register_key)
        if value is None:
            return None
        return bool(int(value) & (1 << self.entity_description.bit_index))
