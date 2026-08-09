# SPDX-License-Identifier: AGPL-3.0-or-later
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
    SNMP_SELF_TEST_SENSOR_DESCRIPTIONS,
)
from .coordinator import APCModbusCoordinator
from .device_types import APCDeviceType
from .external_probe_entities import is_external_probe_entity_available
from .icons_unified import resolve_sensor_icon
from .sensor_availability_unified import is_sensor_enabled_by_default

_LOGGER = logging.getLogger(__name__)


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
        from . import registers_smt_ups

        sensor_descriptions = [
            *registers_smt_ups.SENSOR_DESCRIPTIONS,
            *(
                description
                for capability, description in registers_smt_ups.WRITE_SENSOR_DESCRIPTIONS.items()
                if capability in coordinator.write_capabilities
            ),
        ]
    elif coordinator.device_type == APCDeviceType.SMARTCONNECT_UPS:
        from . import registers_smt_ups

        sensor_descriptions = [
            *registers_smt_ups.SMARTCONNECT_SENSOR_DESCRIPTIONS,
            *(
                description
                for capability, description in registers_smt_ups.WRITE_SENSOR_DESCRIPTIONS.items()
                if capability in coordinator.write_capabilities
            ),
        ]
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

    external_sensor_descriptions = {
        description.key: description
        for description in SNMP_EXTERNAL_SENSOR_DESCRIPTIONS
    }

    # SNMP-backed external probe sensors are available across supported families.
    sensor_descriptions = [*sensor_descriptions, *SNMP_EXTERNAL_SENSOR_DESCRIPTIONS]
    if coordinator.snmp_availability == "available" and coordinator.device_type in (
        APCDeviceType.SMART_UPS,
        APCDeviceType.SMT_UPS,
    ):
        sensor_descriptions = [
            *sensor_descriptions,
            *SNMP_SELF_TEST_SENSOR_DESCRIPTIONS,
        ]
    sensor_descriptions = [
        description
        for description in sensor_descriptions
        if not (
            description.key == "output_energy_rollover"
            and not isinstance(coordinator.data.get("output_energy"), int)
        )
    ]
    sensor_descriptions = [
        description
        for description in sensor_descriptions
        if is_external_probe_entity_available(
            description.key,
            coordinator.data,
            getattr(coordinator, "_snmp_probe_detection", None),
        )
    ]
    added_external_probe_keys = {
        description.key
        for description in sensor_descriptions
        if description.key in external_sensor_descriptions
    }

    _LOGGER.debug(
        "Setting up %d sensors for device type %s",
        len(sensor_descriptions),
        coordinator.device_type.value,
    )

    async_add_entities(
        APCModbusSensor(coordinator, description, entry.entry_id)
        for description in sensor_descriptions
    )

    def _add_newly_detected_external_probe_entities() -> None:
        """Add optional external probe entities detected after setup."""
        detection = getattr(coordinator, "_snmp_probe_detection", None)
        new_descriptions = []
        for key, description in external_sensor_descriptions.items():
            if key in added_external_probe_keys:
                continue
            if not is_external_probe_entity_available(key, coordinator.data, detection):
                continue
            added_external_probe_keys.add(key)
            new_descriptions.append(description)

        if not new_descriptions:
            return

        _LOGGER.info(
            "[%s] Adding %d newly detected SNMP external probe sensor(s): %s",
            coordinator._log_ctx,
            len(new_descriptions),
            ", ".join(
                getattr(description, "name", description.key)
                for description in new_descriptions
            ),
        )
        async_add_entities(
            APCModbusSensor(coordinator, description, entry.entry_id)
            for description in new_descriptions
        )

    entry.async_on_unload(
        coordinator.async_add_listener(_add_newly_detected_external_probe_entities)
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
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
            sw_version=f"{coordinator.fw_version} ({coordinator.fw_date})"
            if coordinator.fw_version and coordinator.fw_date
            else coordinator.fw_version,
        )
        self._attr_icon = resolve_sensor_icon(description.key)
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
            if description.key.endswith("_operation_state")
            else is_sensor_enabled_by_default(
                description.key,
                coordinator.device_type.value,
            )
        )
        # Energy is stored as integer Wh and converted to kWh only for the entity.
        if description.device_class != SensorDeviceClass.ENUM:
            precision = description.suggested_display_precision
            if description.device_class == SensorDeviceClass.ENERGY:
                self._attr_suggested_display_precision = (
                    3 if precision is None else precision
                )
            else:
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

        if self.entity_description.device_class == SensorDeviceClass.ENERGY:
            return value / 1000

        return value
