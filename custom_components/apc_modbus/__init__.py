# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""APC UPS Modbus integration entry point."""

from __future__ import annotations

import logging

try:
    import pymodbus
    PYMODBUS_VERSION = pymodbus.__version__
except (ImportError, AttributeError):
    PYMODBUS_VERSION = "unknown"

from pymodbus.client import ModbusTcpClient
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import (
    CONF_DEVICE_NAME,
    CONF_SNMP_COMMUNITY,
    CONF_UNIT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_UNIT,
    DOMAIN,
    KEY_CLIENT,
    KEY_COORDINATOR,
    SUPPORTED_PLATFORMS,
)
from .coordinator import APCModbusCoordinator
from .device_types import APCDeviceType
from .register_factory import get_registers_for_device

try:
    from .snmp_helper import async_get_device_metadata, detect_device_type
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    async_get_device_metadata = None
    detect_device_type = None

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up APC Modbus from a config entry."""
    _LOGGER.info("APC UPS Modbus integration starting (pymodbus %s)", PYMODBUS_VERSION)
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit = entry.data.get(CONF_UNIT, DEFAULT_UNIT)
    device_name = entry.data.get(CONF_DEVICE_NAME, DEFAULT_NAME)
    snmp_community = entry.data.get(CONF_SNMP_COMMUNITY, DEFAULT_SNMP_COMMUNITY)

    # Create client with timeout to prevent hung connections
    client = ModbusTcpClient(host=host, port=port, timeout=5)
    connected = await hass.async_add_executor_job(client.connect)
    if not connected:
        raise ConfigEntryNotReady("Unable to connect to APC UPS")

    coordinator = APCModbusCoordinator(hass, client, unit, device_name)

    # Query SNMP for device metadata and detect device type (non-blocking, fails gracefully)
    device_type = APCDeviceType.SMART_UPS  # default
    if SNMP_AVAILABLE and async_get_device_metadata and detect_device_type:
        try:
            metadata = await async_get_device_metadata(host, snmp_community)
            coordinator.set_device_metadata(
                hw_model=metadata.get("model"),
                serial_number=metadata.get("serial_number"),
                fw_version=metadata.get("firmware_version"),
                fw_date=metadata.get("firmware_date"),
            )
            # Detect device type from model string
            device_type = detect_device_type(metadata.get("model"))
            coordinator.set_device_type(device_type)
        except Exception as err:
            _LOGGER.warning("Failed to query SNMP metadata from %s: %s", host, err)
            # Continue without metadata - Modbus sensors still work, default to Smart-UPS
            coordinator.set_device_type(APCDeviceType.SMART_UPS)
    else:
        _LOGGER.debug("SNMP not available, defaulting device type to Smart-UPS")
        coordinator.set_device_type(APCDeviceType.SMART_UPS)

    # Load registers for detected device type
    registers, blocks, reg_map = get_registers_for_device(coordinator.device_type)
    coordinator.set_registers(registers, blocks, reg_map)

    # For Rack PDU, discover capabilities for dynamic entity generation
    if coordinator.device_type == APCDeviceType.RACK_PDU:
        try:
            capabilities = await coordinator.async_discover_capabilities()
            if capabilities:
                coordinator.set_capabilities(capabilities)
        except Exception as err:
            _LOGGER.warning("Failed to discover Rack PDU capabilities: %s", err)
            # Continue - will create entities with default capabilities

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        _LOGGER.error("Failed to fetch initial data from APC device: %s", err)
        raise ConfigEntryNotReady(f"Failed to fetch initial data: {err}") from err

    hass.data[DOMAIN][entry.entry_id] = {
        KEY_CLIENT: client,
        KEY_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, SUPPORTED_PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an APC Modbus config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, SUPPORTED_PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(data[KEY_CLIENT].close)

    return unload_ok
