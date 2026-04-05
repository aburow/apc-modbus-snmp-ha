# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Button platform for APC UPS diagnostics."""

from __future__ import annotations

import json
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import async_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KEY_COORDINATOR
from .coordinator import APCModbusCoordinator
from .diagnostic_collector import collect_diagnostic_dump

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up APC Modbus diagnostic button."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][
        KEY_COORDINATOR
    ]
    async_add_entities([APCModbusDiagnosticButton(coordinator, entry.entry_id)])


class APCModbusDiagnosticButton(CoordinatorEntity[APCModbusCoordinator], ButtonEntity):
    """Manual button to run a detailed diagnostic collector dump."""

    has_entity_name = True
    _attr_name = "Run Diagnostics"
    _attr_icon = "mdi:stethoscope"

    def __init__(self, coordinator: APCModbusCoordinator, entry_id: str) -> None:
        """Initialize button entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_run_diagnostics"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.hw_model or "APC Device",
            serial_number=coordinator.serial_number,
        )

    async def async_press(self) -> None:
        """Run diagnostics and show the dump in a persistent-notification modal."""
        dump = await self.hass.async_add_executor_job(
            collect_diagnostic_dump,
            self.coordinator.host,
            self.coordinator.snmp_community,
            self.coordinator.port,
            self.coordinator.unit,
        )

        dump_json = json.dumps(dump, indent=2, sort_keys=False)
        notification_id = f"{DOMAIN}_{self._entry_id}_diagnostics"
        async_create(
            self.hass,
            f"```json\n{dump_json}\n```",
            title=f"{self.coordinator.device_name} Diagnostics",
            notification_id=notification_id,
        )
        _LOGGER.info(
            "Diagnostics dump generated (notification_id=%s)",
            notification_id,
        )
