# SPDX-License-Identifier: AGPL-3.0-or-later
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

from homeassistant.const import CONF_SCAN_INTERVAL

from .const import (
    CONF_DETECTION_VERSION,
    CONF_DEVICE_TYPE,
    CONF_KEEP_CONNECTION_OPEN,
    CONF_SNMP_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_PORT,
    DOMAIN,
    KEY_COORDINATOR,
)
from .coordinator import APCModbusCoordinator
from .device_types import DETECTION_VERSION, choose_device_type
from .diagnostic_collector import collect_diagnostic_dump
from .entity_defaults import async_reset_entry_monitors_to_defaults

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
    async_add_entities(
        [
            APCModbusDiagnosticButton(coordinator, entry),
            APCModbusRedetectDeviceTypeButton(coordinator, entry),
            APCModbusResetMonitorDefaultsButton(coordinator, entry.entry_id),
        ]
    )


class APCModbusDiagnosticButton(CoordinatorEntity[APCModbusCoordinator], ButtonEntity):
    """Manual button to run a detailed diagnostic collector dump."""

    has_entity_name = True
    _attr_name = "Run Diagnostics"
    _attr_icon = "mdi:stethoscope"

    def __init__(self, coordinator: APCModbusCoordinator, entry: ConfigEntry) -> None:
        """Initialize button entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_run_diagnostics"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    async def async_press(self) -> None:
        """Run diagnostics and show the dump in a persistent-notification modal."""
        dump = await self.hass.async_add_executor_job(
            collect_diagnostic_dump,
            self.coordinator.host,
            self.coordinator.snmp_community,
            self.coordinator.port,
            self.coordinator.unit,
            self._entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            self._entry.data.get(CONF_KEEP_CONNECTION_OPEN, False),
            self._entry.data.get(CONF_SNMP_PORT, DEFAULT_SNMP_PORT),
            self.coordinator.transport_mode,
            self.coordinator.transport_promotion_reason,
            self.coordinator.snmp_availability,
        )

        dump_json = json.dumps(dump, indent=2, sort_keys=False)
        notification_id = f"{DOMAIN}_{self._entry.entry_id}_diagnostics"
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


class APCModbusRedetectDeviceTypeButton(
    CoordinatorEntity[APCModbusCoordinator], ButtonEntity
):
    """Manual button to re-run device-type detection and reload the entry."""

    has_entity_name = True
    _attr_name = "Re-detect Device Type"
    _attr_icon = "mdi:magnify-scan"

    def __init__(self, coordinator: APCModbusCoordinator, entry: ConfigEntry) -> None:
        """Initialize button entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_redetect_device_type"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    async def async_press(self) -> None:
        """Run Modbus device detection again and reload if the result changed."""
        snmp_retry_succeeded = await self.coordinator.async_retry_snmp_metadata()
        detected_device_type = await self.coordinator.async_detect_device_type()
        selected_device_type = choose_device_type(
            stored_device_type=self.coordinator.device_type,
            detected_device_type=detected_device_type,
        )

        entry_data = self._entry.data
        stored_detection_version = entry_data.get(CONF_DETECTION_VERSION)
        config_changed = (
            entry_data.get(CONF_DEVICE_TYPE) != selected_device_type.value
            or stored_detection_version != DETECTION_VERSION
        )

        if config_changed:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={
                    **entry_data,
                    CONF_DEVICE_TYPE: selected_device_type.value,
                    CONF_DETECTION_VERSION: DETECTION_VERSION,
                },
            )
            await self.hass.config_entries.async_reload(self._entry.entry_id)
            message = (
                f"Device type resolved as `{selected_device_type.value}` and the "
                "integration entry was reloaded. "
                f"SNMP retry {'succeeded' if snmp_retry_succeeded else 'failed'}."
            )
        else:
            await self.coordinator.async_request_refresh()
            message = (
                f"Device type remains `{selected_device_type.value}`. "
                "No reload was required. "
                f"Explicit SNMP retry {'succeeded' if snmp_retry_succeeded else 'failed'}."
            )

        notification_id = f"{DOMAIN}_{self._entry.entry_id}_redetect_device_type"
        async_create(
            self.hass,
            message,
            title=f"{self.coordinator.device_name} Device Type",
            notification_id=notification_id,
        )
        _LOGGER.info(
            "Manual device re-detect completed for entry %s: %s",
            self._entry.entry_id,
            selected_device_type.value,
        )


class APCModbusResetMonitorDefaultsButton(
    CoordinatorEntity[APCModbusCoordinator], ButtonEntity
):
    """Manual button to reset monitor enablement to integration defaults."""

    has_entity_name = True
    _attr_name = "Reset Monitor Defaults"
    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator: APCModbusCoordinator, entry_id: str) -> None:
        """Initialize button entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_reset_monitor_defaults"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    async def async_press(self) -> None:
        """Reset enabled/disabled entities to integration defaults."""
        device_type = self.coordinator.device_type
        device_family = device_type.value if device_type is not None else "unknown"
        (
            enabled_count,
            disabled_count,
            unchanged_count,
        ) = await async_reset_entry_monitors_to_defaults(
            self.hass,
            entry_id=self._entry_id,
            device_family=device_family,
        )

        notification_id = f"{DOMAIN}_{self._entry_id}_reset_monitor_defaults"
        message = (
            "Monitor defaults applied.\n\n"
            f"- Enabled: {enabled_count}\n"
            f"- Disabled: {disabled_count}\n"
            f"- Unchanged: {unchanged_count}"
        )
        async_create(
            self.hass,
            message,
            title=f"{self.coordinator.device_name} Monitor Defaults",
            notification_id=notification_id,
        )
        _LOGGER.info(
            "Monitor defaults reset for entry %s (enabled=%d disabled=%d unchanged=%d)",
            self._entry_id,
            enabled_count,
            disabled_count,
            unchanged_count,
        )
