# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""APC UPS Modbus integration entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime

try:
    import pymodbus

    PYMODBUS_VERSION = pymodbus.__version__
except (ImportError, AttributeError):
    PYMODBUS_VERSION = "unknown"

from pymodbus.client import ModbusTcpClient
from homeassistant.config_entries import ConfigEntry
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.const import CONF_HOST, CONF_PORT
import voluptuous as vol

from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_TYPE,
    CONF_DEBUG_DUMP,
    CONF_SNMP_COMMUNITY,
    CONF_UNIT,
    DEFAULT_DEBUG_DUMP,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_UNIT,
    DOMAIN,
    KEY_CLIENT,
    KEY_COORDINATOR,
    SERVICE_DEBUG_DUMP,
    SERVICE_FIELD_ENTRY_ID,
    SUPPORTED_PLATFORMS,
)
from .coordinator import APCModbusCoordinator
from .device_types import APCDeviceType
from .register_factory import get_registers_for_device
from .snmp_helper import get_device_metadata_sync

_LOGGER = logging.getLogger(__name__)

SERVICE_DEBUG_DUMP_SCHEMA = vol.Schema(
    {
        vol.Required(SERVICE_FIELD_ENTRY_ID): str,
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the APC Modbus integration (service registration)."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.services.has_service(DOMAIN, SERVICE_DEBUG_DUMP):

        async def _handle_debug_dump(call):
            entry_id = call.data[SERVICE_FIELD_ENTRY_ID]
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is None:
                raise HomeAssistantError(f"Config entry not found: {entry_id}")

            if not entry.options.get(CONF_DEBUG_DUMP, DEFAULT_DEBUG_DUMP):
                raise HomeAssistantError(
                    "Debug dump is disabled for this device. Enable it in options first."
                )

            entry_data = dict(entry.data)
            if CONF_SNMP_COMMUNITY in entry_data:
                entry_data[CONF_SNMP_COMMUNITY] = "***"

            data = hass.data.get(DOMAIN, {}).get(entry_id)
            if not data:
                raise HomeAssistantError(
                    "Entry data not available (integration not loaded)."
                )

            coordinator: APCModbusCoordinator = data[KEY_COORDINATOR]
            client: ModbusTcpClient = data[KEY_CLIENT]

            dump = {
                "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "entry_id": entry_id,
                "pymodbus_version": PYMODBUS_VERSION,
                "config": entry_data,
                "options": dict(entry.options),
                "device": {
                    "name": coordinator.device_name,
                    "host": coordinator.host,
                    "port": coordinator.port,
                    "unit": coordinator.unit,
                    "device_type": coordinator.device_type.value,
                    "hw_model": coordinator.hw_model,
                    "serial_number": coordinator.serial_number,
                    "fw_version": coordinator.fw_version,
                    "fw_date": coordinator.fw_date,
                },
                "registers": {
                    "registers": coordinator.registers,
                    "register_blocks": coordinator.register_blocks,
                    "register_map": coordinator.register_map,
                },
                "data": coordinator.data,
                "client": {
                    "connected": client.connected,
                },
            }

            dump_dir = hass.config.path("apc_modbus_debug")
            os.makedirs(dump_dir, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            filename = f"apc_modbus_debug_{entry_id}_{timestamp}.json"
            filepath = os.path.join(dump_dir, filename)

            def _write():
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(dump, f, indent=2, sort_keys=True, default=str)

            await hass.async_add_executor_job(_write)

            message = f"APC Modbus debug dump written to {filepath}"
            _LOGGER.info(message)
            persistent_notification.async_create(
                hass, message, title="APC Modbus Debug Dump"
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_DEBUG_DUMP,
            _handle_debug_dump,
            schema=SERVICE_DEBUG_DUMP_SCHEMA,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up APC Modbus from a config entry."""
    _LOGGER.info("APC UPS Modbus integration starting (pymodbus %s)", PYMODBUS_VERSION)
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit = entry.data.get(CONF_UNIT, DEFAULT_UNIT)
    device_name = entry.data.get(CONF_DEVICE_NAME, DEFAULT_NAME)
    snmp_community = entry.data.get(CONF_SNMP_COMMUNITY, DEFAULT_SNMP_COMMUNITY)
    device_type_str = entry.data.get(CONF_DEVICE_TYPE, APCDeviceType.SMART_UPS.value)
    # Convert string to enum
    device_type = (
        APCDeviceType(device_type_str) if device_type_str else APCDeviceType.SMART_UPS
    )

    # Create client with timeout to prevent hung connections
    client = ModbusTcpClient(host=host, port=port, timeout=5)
    connected = await hass.async_add_executor_job(client.connect)
    if not connected:
        raise ConfigEntryNotReady("Unable to connect to APC UPS")

    # Shared lock per host:port to prevent overlapping I/O across entries for same device.
    locks = hass.data[DOMAIN].setdefault("locks", {})
    lock_key = f"{host}:{port}"
    io_lock = locks.setdefault(lock_key, asyncio.Lock())

    coordinator = APCModbusCoordinator(
        hass,
        client,
        unit,
        device_name,
        host,
        port,
        entry.entry_id,
        5,
        io_lock,
    )

    coordinator.set_device_type(device_type)

    # Query SNMP for device metadata (async, non-blocking)
    try:
        _LOGGER.debug(
            "Querying SNMP metadata from %s (entry_id=%s)", host, entry.entry_id
        )
        metadata = await hass.async_add_executor_job(
            get_device_metadata_sync, host, snmp_community, device_type
        )
        if metadata and any(
            [
                metadata.get("model"),
                metadata.get("serial_number"),
                metadata.get("firmware_version"),
            ]
        ):
            _LOGGER.info(
                "SNMP metadata retrieved: model=%s, serial=%s",
                metadata.get("model"),
                metadata.get("serial_number"),
            )
            coordinator.set_device_metadata(
                hw_model=metadata.get("model"),
                serial_number=metadata.get("serial_number"),
                fw_version=metadata.get("firmware_version"),
                fw_date=metadata.get("firmware_date"),
            )
        else:
            _LOGGER.debug("SNMP query returned empty metadata")
    except (OSError, TimeoutError, RuntimeError, ValueError) as err:
        _LOGGER.warning("Failed to query SNMP metadata from %s: %s", host, err)
        # Continue without metadata - Modbus sensors still work

    # Load registers for detected device type
    registers, blocks, reg_map = get_registers_for_device(coordinator.device_type)
    coordinator.set_registers(registers, blocks, reg_map)

    # For Rack PDU, discover capabilities for dynamic entity generation
    if coordinator.device_type == APCDeviceType.RACK_PDU:
        try:
            capabilities = await coordinator.async_discover_capabilities()
            if capabilities:
                coordinator.set_capabilities(capabilities)
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
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
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, SUPPORTED_PLATFORMS
    )

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(data[KEY_CLIENT].close)

    return unload_ok
