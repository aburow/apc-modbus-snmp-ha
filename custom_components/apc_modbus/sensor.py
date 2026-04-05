# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Sensor platform for APC UPS data."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    APCModbusSensorDescription,
    DOMAIN,
    KEY_COORDINATOR,
    SNMP_EXTERNAL_SENSOR_DESCRIPTIONS,
)
from .coordinator import APCModbusCoordinator
from .device_types import APCDeviceType

_LOGGER = logging.getLogger(__name__)

OPTIONAL_SNMP_EXTERNAL_KEYS = {
    "snmp_external_temp_1",
    "snmp_external_humidity_1",
    "snmp_external_temp_2",
    "snmp_external_humidity_2",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the APC UPS sensors for a config entry."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][
        KEY_COORDINATOR
    ]

    # Get device-type-specific sensor descriptions
    if coordinator.device_type == APCDeviceType.SMART_UPS:
        # Smart-UPS uses static sensor descriptions from const
        from .const import SENSOR_DESCRIPTIONS

        sensor_descriptions = SENSOR_DESCRIPTIONS
    elif coordinator.device_type == APCDeviceType.SMT_UPS:
        # SMT/SMX/SRT uses static sensor descriptions from its register module
        from . import registers_smt_ups

        sensor_descriptions = registers_smt_ups.SENSOR_DESCRIPTIONS
    elif coordinator.device_type == APCDeviceType.RACK_PDU:
        # Rack PDU uses dynamic sensor descriptions based on capabilities
        from . import registers_rack_pdu

        sensor_descriptions = registers_rack_pdu.get_sensor_descriptions(
            coordinator.device_capabilities
        )
    else:
        # Unknown type defaults to Smart-UPS sensor descriptions
        from .const import SENSOR_DESCRIPTIONS

        sensor_descriptions = SENSOR_DESCRIPTIONS

    # SNMP-backed external probe sensors are available across supported families.
    sensor_descriptions = [*sensor_descriptions, *SNMP_EXTERNAL_SENSOR_DESCRIPTIONS]
    sensor_descriptions = [
        description
        for description in sensor_descriptions
        if description.key not in OPTIONAL_SNMP_EXTERNAL_KEYS
        or coordinator.data.get(description.register_key) is not None
    ]

    _LOGGER.debug(
        "Setting up %d sensors for device type %s",
        len(sensor_descriptions),
        coordinator.device_type.value,
    )

    async_add_entities(
        APCModbusSensor(coordinator, description, entry.entry_id)
        for description in sensor_descriptions
    )


class APCModbusSensor(CoordinatorEntity, SensorEntity):
    """Representation of an APC UPS Modbus sensor."""

    has_entity_name = True

    def __init__(
        self,
        coordinator: APCModbusCoordinator,
        description: APCModbusSensorDescription,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.hw_model or "Smart-UPS",
            serial_number=coordinator.serial_number,
            sw_version=f"{coordinator.fw_version} ({coordinator.fw_date})"
            if coordinator.fw_version and coordinator.fw_date
            else coordinator.fw_version,
        )
        # Keep numeric UI rendering concise across all device families.
        if description.device_class != SensorDeviceClass.ENUM:
            precision = description.suggested_display_precision
            self._attr_suggested_display_precision = (
                1 if precision is None else min(precision, 1)
            )

    @property
    def native_value(self):
        """Return the latest value from the coordinator."""
        value = self.coordinator.data.get(self.entity_description.register_key)
        if value is None:
            return None

        if self.entity_description.value_map:
            try:
                code = int(value)
            except (TypeError, ValueError):
                return None
            return self.entity_description.value_map.get(code, f"Unknown ({code})")

        return value
