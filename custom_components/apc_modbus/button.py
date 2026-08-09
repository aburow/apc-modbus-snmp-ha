# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Button platform for APC UPS diagnostics."""

from __future__ import annotations

import json
import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.components.logbook import async_log_entry
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
from .device_types import DETECTION_VERSION, choose_device_type, device_type_label
from .diagnostic_collector import collect_diagnostic_dump
from .entity_defaults import async_reset_entry_monitors_to_defaults
from .write_support import (
    OUTLET_CAPABILITIES,
    OutletAction,
    WriteCapability,
    WriteOperation,
)

_LOGGER = logging.getLogger(__name__)


class _APCModbusRestorationButton:
    """Clarify a retained native button timestamp after availability recovery."""

    _report_restoration = False
    _restoration_was_unavailable = False
    _restoration_context = None

    def _mark_restoration_candidate(self) -> None:
        self._report_restoration = True
        self._restoration_was_unavailable = False
        self._restoration_context = getattr(self, "_context", None)

    def _clear_restoration_candidate(self) -> None:
        self._report_restoration = False
        self._restoration_was_unavailable = False
        self._restoration_context = None

    def _complete_restoration_candidate(self) -> None:
        """Discard an arm that did not observe the press-related outage."""
        if not self._restoration_was_unavailable:
            self._clear_restoration_candidate()

    def _restoration_message(self) -> str:
        return "Control restored to available; this is not another press."

    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        if not self._report_restoration:
            return
        if not self.available:
            self._restoration_was_unavailable = True
            return
        if not self._restoration_was_unavailable:
            return
        context = self._restoration_context
        self._clear_restoration_candidate()
        async_log_entry(
            self.hass,
            self.name or "APC control",
            self._restoration_message(),
            domain=DOMAIN,
            entity_id=self.entity_id,
            context=context,
        )


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
    for target, capability in OUTLET_CAPABILITIES.items():
        if capability.value not in coordinator.write_capabilities:
            continue
        entities.extend(
            APCModbusWriteButton(
                coordinator,
                entry,
                WriteOperation.OUTLET,
                f"{target.value}:{action.value}",
                f"outlet_{target.value}_{action.value}",
            )
            for action in (
                OutletAction.SHUTDOWN,
                OutletAction.REBOOT,
                OutletAction.CANCEL,
            )
        )
    for capability, operations in (
        (
            WriteCapability.BATTERY_TEST,
            (WriteOperation.BATTERY_TEST_START, WriteOperation.BATTERY_TEST_ABORT),
        ),
        (
            WriteCapability.RUNTIME_CALIBRATION,
            (WriteOperation.CALIBRATION_START, WriteOperation.CALIBRATION_ABORT),
        ),
    ):
        if capability.value in coordinator.write_capabilities:
            entities.extend(
                APCModbusWriteButton(
                    coordinator, entry, operation, None, operation.value
                )
                for operation in operations
            )
    async_add_entities(entities)


class APCModbusDiagnosticButton(
    _APCModbusRestorationButton, CoordinatorEntity[APCModbusCoordinator], ButtonEntity
):
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
        self._mark_restoration_candidate()
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
            self._clear_restoration_candidate()
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
        self._complete_restoration_candidate()


class APCModbusRedetectDeviceTypeButton(
    _APCModbusRestorationButton, CoordinatorEntity[APCModbusCoordinator], ButtonEntity
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
        self._mark_restoration_candidate()
        try:
            snmp_retry_succeeded = await self.coordinator.async_retry_snmp_metadata()
            detected_device_type = await self.coordinator.async_detect_device_type()
        except Exception:
            self._clear_restoration_candidate()
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
        self._complete_restoration_candidate()


class APCModbusResetMonitorDefaultsButton(
    _APCModbusRestorationButton, CoordinatorEntity[APCModbusCoordinator], ButtonEntity
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
        self._mark_restoration_candidate()
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
            self._clear_restoration_candidate()
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
        self._complete_restoration_candidate()


class APCModbusWriteButton(
    _APCModbusRestorationButton, CoordinatorEntity[APCModbusCoordinator], ButtonEntity
):
    """One fixed, capability-gated APC command button."""

    has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: APCModbusCoordinator,
        entry: ConfigEntry,
        operation: WriteOperation,
        target: str | None,
        translation_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._operation = operation
        self._target = target
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_write_{translation_key}"
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
        return bool(
            self.coordinator.last_update_success
            and self.coordinator.write_operation_available(
                self._operation.value, self._target
            )
        )

    async def async_press(self) -> None:
        self._mark_restoration_candidate()
        try:
            await self.coordinator.async_execute_write(
                self._operation.value, self._target
            )
        except Exception:
            self._clear_restoration_candidate()
            raise
        self._complete_restoration_candidate()

    def _restoration_message(self) -> str:
        """Describe the existing companion state without claiming completion."""
        status = self._operation_status()
        terminal = {"passed", "failed", "refused", "aborted", "on", "off"}
        descriptor = (
            "Terminal status" if status in terminal else "Current device status"
        )
        return (
            "Control restored to available; this is not another press. "
            f"{descriptor}: {status.capitalize()}."
        )

    def _operation_status(self) -> str:
        """Return the existing companion status without another device read."""
        if self._target:
            state_key = f"outlet_{self._target.partition(':')[0]}_operation_state"
        elif self._operation in (
            WriteOperation.BATTERY_TEST_START,
            WriteOperation.BATTERY_TEST_ABORT,
        ):
            state_key = "battery_test_operation_state"
        else:
            state_key = "runtime_calibration_operation_state"
        return str(self.coordinator.data.get(state_key, "unknown")).replace("_", " ")
