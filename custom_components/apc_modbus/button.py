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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.loader import async_get_integration

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
from .device_types import DETECTION_VERSION, choose_device_type, device_type_label
from .diagnostic_collector import collect_diagnostic_dump
from .device_profiles import get_device_profile
from .entity_defaults import async_reset_entry_monitors_to_defaults
from .modbus_commands import OUTLET_TARGET_BITS, get_command
from .snmp_commands import LEGACY_SNMP_COMMANDS
from .snmp_helper import async_set_snmp_integer


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
    entities = [
        APCModbusDiagnosticButton(coordinator, entry),
        APCModbusRedetectDeviceTypeButton(coordinator, entry),
        APCModbusResetMonitorDefaultsButton(coordinator, entry.entry_id),
    ]
    profile = get_device_profile(coordinator.device_type)
    for command_key in sorted(profile.command_operations):
        targets = OUTLET_TARGET_BITS if command_key.startswith("outlet_") else (None,)
        entities.extend(
            APCModbusCommandButton(coordinator, entry, command_key, target)
            for target in targets
        )
    entities.extend(
        APCSnmpCommandButton(coordinator, entry, command_key)
        for command_key in sorted(profile.snmp_command_operations)
    )
    command_unique_ids = {
        entity.unique_id
        for entity in entities
        if isinstance(entity, (APCModbusCommandButton, APCSnmpCommandButton))
    }
    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if (
            entity_entry.unique_id in command_unique_ids
            and entity_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        ):
            entity_registry.async_update_entity(
                entity_entry.entity_id, disabled_by=None
            )
    async_add_entities(entities)


class APCModbusCommandButton(CoordinatorEntity[APCModbusCoordinator], ButtonEntity):
    """Fixed command for supervised physical validation."""

    has_entity_name = True

    def __init__(
        self,
        coordinator: APCModbusCoordinator,
        entry: ConfigEntry,
        key: str,
        target: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._command = get_command(key, target)
        self._attr_name = self._command.name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{self._command.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        integration = await async_get_integration(self.hass, DOMAIN)
        _LOGGER.debug(
            "[%s] Command test requested: plugin_version=%s, action=%s, model=%s, sku=%s, firmware=%s",
            self.coordinator._log_ctx,
            integration.manifest.get("version", "unknown"),
            self._command.key,
            self.coordinator.raw_modbus_model or self.coordinator.hw_model,
            self.coordinator.raw_modbus_sku,
            self.coordinator.raw_modbus_firmware or self.coordinator.fw_version,
        )
        await self.coordinator.transport.write(
            self._command.address,
            self._command.words,
            command_name=self._command.key,
            # This APC NMC accepts function 16 for command registers and
            # rejects function 6 even for one-register command values.
            force_multiple=True,
        )


class APCSnmpCommandButton(CoordinatorEntity[APCModbusCoordinator], ButtonEntity):
    """One documented PowerNet SNMP command."""

    has_entity_name = True

    def __init__(
        self, coordinator: APCModbusCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self._command = LEGACY_SNMP_COMMANDS[key]
        self._attr_name = self._command.name
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_{self._command.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await async_set_snmp_integer(
            self.coordinator.host,
            self._command.oid,
            self._command.value,
            self.coordinator.snmp_write_community,
            self.coordinator.snmp_port,
        )


class APCModbusDiagnosticButton(CoordinatorEntity[APCModbusCoordinator], ButtonEntity):
    """Manual button to run a detailed diagnostic collector dump."""

    has_entity_name = True
    _attr_name = "Run plugin diagnostics"
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
        try:
            async with self.coordinator._io_lock:
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
        except Exception:
            raise

        dump_json = json.dumps(dump, indent=2, sort_keys=False)
        notification_id = f"{DOMAIN}_{self._entry.entry_id}_diagnostics"
        async_create(
            self.hass,
            f"```json\n{dump_json}\n```",
            title=f"{self.coordinator.device_name} Diagnostics",
            notification_id=notification_id,
        )
        _LOGGER.info("[%s] Diagnostics dump generated.", self.coordinator._log_ctx)


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
        try:
            snmp_retry_succeeded = await self.coordinator.async_retry_snmp_metadata()
            detected_device_type = await self.coordinator.async_detect_device_type()
        except Exception:
            raise
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
                f"Modbus detection resolved {device_type_label(selected_device_type)}. "
                "The integration entry was reloaded. "
                f"Optional SNMP enrichment {'succeeded' if snmp_retry_succeeded else 'was unavailable'}; "
                "no user action is required."
            )
        else:
            await self.coordinator.async_request_refresh()
            message = (
                f"Modbus detection remains {device_type_label(selected_device_type)}. "
                "No reload was required. "
                f"Optional SNMP enrichment {'succeeded' if snmp_retry_succeeded else 'was unavailable'}; "
                "no user action is required."
            )

        notification_id = f"{DOMAIN}_{self._entry.entry_id}_redetect_device_type"
        async_create(
            self.hass,
            message,
            title=f"{self.coordinator.device_name} Device Type",
            notification_id=notification_id,
        )
        _LOGGER.info(
            "[%s] Manual device re-detect completed: %s.",
            self.coordinator._log_ctx,
            device_type_label(selected_device_type),
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
        try:
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
        except Exception:
            raise

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
            "[%s] Monitor defaults reset (enabled=%d disabled=%d unchanged=%d).",
            self.coordinator._log_ctx,
            enabled_count,
            disabled_count,
            unchanged_count,
        )
