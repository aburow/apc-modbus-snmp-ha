# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery installation-date configuration for SMT-compatible UPSs."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, KEY_COORDINATOR
from .coordinator import APCModbusCoordinator
from .device_types import APCDeviceType
from .registers_smt_ups import BATTERY_DATE_EPOCH, _battery_date

_BATTERY_DATE_SETTING_ADDRESS = 0x0253


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the documented SMT battery-installation date setting."""
    coordinator: APCModbusCoordinator = hass.data[DOMAIN][entry.entry_id][
        KEY_COORDINATOR
    ]
    if coordinator.device_type not in (
        APCDeviceType.SMT_UPS,
        APCDeviceType.SMARTCONNECT_UPS,
    ):
        return
    async_add_entities([APCModbusBatteryInstallationDate(coordinator, entry)])


class APCModbusBatteryInstallationDate(
    CoordinatorEntity[APCModbusCoordinator], DateEntity
):
    """The documented persistent Battery.DateSetting register."""

    has_entity_name = True
    _attr_name = "Battery Installation Date"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: APCModbusCoordinator, entry: ConfigEntry) -> None:
        """Initialize the date entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_battery_installation_date"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="APC",
            model=coordinator.get_device_model_for_registry(),
            serial_number=coordinator.serial_number,
            configuration_url=coordinator.get_configuration_url_for_registry(),
        )

    @property
    def native_value(self) -> date | None:
        """Return the configured installation date."""
        return _battery_date(
            self.coordinator.data.get("battery_installation_date_days")
        )

    async def async_set_value(self, value: date) -> None:
        """Persist one documented installation date without read-modify-write."""
        days = (value - BATTERY_DATE_EPOCH).days
        if not 0 <= days <= 0xFFFF:
            raise HomeAssistantError("battery_installation_date_out_of_range")
        await self.coordinator.transport.write(
            _BATTERY_DATE_SETTING_ADDRESS,
            (days,),
            command_name="battery_installation_date",
            force_multiple=True,
        )
        await self.coordinator.async_request_refresh()
