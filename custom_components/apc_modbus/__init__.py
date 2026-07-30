# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""APC UPS Modbus integration entry point."""

from __future__ import annotations

import asyncio
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
from homeassistant.helpers import entity_registry as er
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL

from .const import (
    CONF_DETECTION_VERSION,
    CONF_DEVICE_NAME,
    CONF_DEVICE_TYPE,
    CONF_KEEP_CONNECTION_OPEN,
    CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS,
    CONF_SNMP_COMMUNITY,
    CONF_SNMP_PORT,
    CONF_UNIT,
    DEFAULT_KEEP_CONNECTION_OPEN,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SNMP_COMMUNITY,
    DEFAULT_SNMP_PORT,
    DEFAULT_UNIT,
    DOMAIN,
    KEY_CLIENT,
    KEY_COORDINATOR,
    SUPPORTED_PLATFORMS,
)
from .coordinator import APCModbusCoordinator
from .device_types import (
    DETECTION_VERSION,
    APCDeviceType,
    choose_device_type,
    is_concrete_device_type,
    should_probe_device_type,
)
from .external_probe_entities import filter_available_external_probe_keys
from .register_factory import get_registers_for_device
from .scan_interval_guard import compute_effective_scan_interval
from .snmp_helper import detect_device_type, get_device_metadata_sync
from .startup_stagger import compute_startup_stagger_delay

_LOGGER = logging.getLogger(__name__)


def _get_expected_entity_unique_ids(
    coordinator: APCModbusCoordinator, entry_id: str
) -> set[str]:
    """Build expected unique_ids for current device type and capabilities."""
    if coordinator.device_type == APCDeviceType.SMART_UPS:
        from .const import (
            BINARY_SENSOR_DESCRIPTIONS,
            SENSOR_DESCRIPTIONS,
            SNMP_EXTERNAL_SENSOR_DESCRIPTIONS,
        )

        sensor_keys = {
            description.key
            for description in [
                *SENSOR_DESCRIPTIONS,
                *SNMP_EXTERNAL_SENSOR_DESCRIPTIONS,
            ]
        }
        binary_keys = {description.key for description in BINARY_SENSOR_DESCRIPTIONS}
    elif coordinator.device_type == APCDeviceType.SMT_UPS:
        from . import registers_smt_ups
        from .const import SNMP_EXTERNAL_SENSOR_DESCRIPTIONS

        sensor_keys = {
            description.key
            for description in [
                *registers_smt_ups.SENSOR_DESCRIPTIONS,
                *SNMP_EXTERNAL_SENSOR_DESCRIPTIONS,
            ]
        }
        binary_keys = {
            description.key
            for description in registers_smt_ups.BINARY_SENSOR_DESCRIPTIONS
        }
    elif coordinator.device_type == APCDeviceType.RACK_PDU:
        from . import registers_rack_pdu
        from .const import SNMP_EXTERNAL_SENSOR_DESCRIPTIONS

        sensor_descriptions = registers_rack_pdu.get_sensor_descriptions(
            coordinator.device_capabilities
        )
        binary_descriptions = registers_rack_pdu.get_binary_sensor_descriptions(
            coordinator.device_capabilities
        )
        sensor_keys = {
            description.key
            for description in [
                *sensor_descriptions,
                *SNMP_EXTERNAL_SENSOR_DESCRIPTIONS,
            ]
        }
        binary_keys = {description.key for description in binary_descriptions}
    else:
        return set()

    sensor_keys = filter_available_external_probe_keys(
        sensor_keys,
        coordinator.data,
        getattr(coordinator, "_snmp_probe_detection", None),
    )

    all_keys = sensor_keys | binary_keys
    return {f"{DOMAIN}_{entry_id}_{key}" for key in all_keys}


async def _async_cleanup_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: APCModbusCoordinator
) -> None:
    """Remove stale entities left over from previous device-type classifications."""
    ent_reg = er.async_get(hass)
    expected_unique_ids = _get_expected_entity_unique_ids(coordinator, entry.entry_id)
    if not expected_unique_ids:
        return

    prefix = f"{DOMAIN}_{entry.entry_id}_"
    removed_count = 0

    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity_entry.domain not in {"sensor", "binary_sensor"}:
            continue
        if not entity_entry.unique_id or not entity_entry.unique_id.startswith(prefix):
            continue
        if entity_entry.unique_id in expected_unique_ids:
            continue
        ent_reg.async_remove(entity_entry.entity_id)
        removed_count += 1

    if removed_count:
        _LOGGER.info(
            "Removed %d stale entities for entry %s after device type resolution",
            removed_count,
            entry.entry_id,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up APC Modbus from a config entry."""
    _LOGGER.info("APC UPS Modbus integration starting (pymodbus %s)", PYMODBUS_VERSION)
    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    unit = entry.data.get(CONF_UNIT, DEFAULT_UNIT)
    device_name = entry.data.get(CONF_DEVICE_NAME, DEFAULT_NAME)
    snmp_community = entry.data.get(CONF_SNMP_COMMUNITY, DEFAULT_SNMP_COMMUNITY)
    snmp_port = entry.data.get(CONF_SNMP_PORT, DEFAULT_SNMP_PORT)
    keep_connection_open = entry.data.get(
        CONF_KEEP_CONNECTION_OPEN, DEFAULT_KEEP_CONNECTION_OPEN
    )
    configured_scan_interval = entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    device_type_str = entry.data.get(CONF_DEVICE_TYPE)
    device_type = APCDeviceType(device_type_str) if device_type_str else None
    detection_version = entry.data.get(CONF_DETECTION_VERSION)
    entry_ids = [
        config_entry.entry_id
        for config_entry in hass.config_entries.async_entries(DOMAIN)
    ]
    scan_interval = compute_effective_scan_interval(
        configured_scan_interval,
        len(entry_ids),
    )
    if scan_interval != configured_scan_interval:
        _LOGGER.warning(
            "Fleet-aware polling guard raised scan interval for %s from %ss to %ss "
            "(%d APC entries configured). Increase this entry's scan interval in "
            "UI settings to match if you want this persisted.",
            entry.entry_id,
            configured_scan_interval,
            scan_interval,
            len(entry_ids),
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
        snmp_community,
        snmp_port,
        scan_interval,
        keep_connection_open=keep_connection_open,
        output_energy_completed_rollovers=entry.data.get(
            CONF_OUTPUT_ENERGY_COMPLETED_ROLLOVERS, 0
        ),
    )

    startup_stagger_delay = compute_startup_stagger_delay(
        entry_ids, entry.entry_id, scan_interval
    )
    if startup_stagger_delay > 0:
        _LOGGER.info(
            "Applying startup stagger of %.1fs for entry %s across %d APC devices",
            startup_stagger_delay,
            entry.entry_id,
            len(entry_ids),
        )
        await asyncio.sleep(startup_stagger_delay)

    selected_device_type = device_type
    original_device_type = device_type

    snmp_hint_device_type: APCDeviceType | None = None
    detected_device_type: APCDeviceType | None = None

    # Query SNMP for device metadata (async, non-blocking)
    try:
        _LOGGER.debug(
            "Querying SNMP metadata from %s (entry_id=%s)", host, entry.entry_id
        )
        metadata = await hass.async_add_executor_job(
            get_device_metadata_sync,
            host,
            snmp_community,
            device_type,
            snmp_port,
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
                mark_refresh_complete=False,
            )
            if metadata.get("model"):
                snmp_hint_device_type = detect_device_type(metadata.get("model"))
            if snmp_hint_device_type == APCDeviceType.RACK_PDU:
                _LOGGER.info(
                    "SNMP metadata strongly suggests a Rack PDU model: %s",
                    metadata.get("model"),
                )
        else:
            _LOGGER.debug("SNMP query returned empty metadata")
    except (OSError, TimeoutError, RuntimeError, ValueError) as err:
        _LOGGER.warning("Failed to query SNMP metadata from %s: %s", host, err)
        # Continue without metadata - Modbus sensors still work

    if should_probe_device_type(
        selected_device_type,
        stored_detection_version=detection_version,
        snmp_hint_device_type=snmp_hint_device_type,
    ):
        try:
            detected_device_type = await coordinator.async_detect_device_type()
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            _LOGGER.warning("Failed to auto-detect device type via Modbus: %s", err)
        else:
            if detected_device_type:
                _LOGGER.info(
                    "Auto-detected device type as %s based on Modbus probe",
                    detected_device_type.value,
                )
                selected_device_type = detected_device_type
            elif is_concrete_device_type(original_device_type):
                _LOGGER.warning(
                    "Device type re-detection was ambiguous; keeping stored type %s",
                    original_device_type.value,
                )

    selected_device_type = choose_device_type(
        stored_device_type=original_device_type,
        detected_device_type=detected_device_type,
        snmp_hint_device_type=snmp_hint_device_type,
    )
    if detected_device_type is None and original_device_type is None:
        if is_concrete_device_type(snmp_hint_device_type):
            _LOGGER.warning(
                "Device type auto-detection via Modbus was ambiguous; using SNMP hint %s instead",
                selected_device_type.value,
            )
        else:
            _LOGGER.warning(
                "Device type auto-detection was ambiguous; defaulting to %s",
                selected_device_type.value,
            )

    # Persist corrected/derived concrete device type and detection version.
    if is_concrete_device_type(selected_device_type) and (
        selected_device_type != original_device_type
        or detection_version != DETECTION_VERSION
    ):
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_DEVICE_TYPE: selected_device_type.value,
                CONF_DETECTION_VERSION: DETECTION_VERSION,
            },
        )

    coordinator.set_device_type(selected_device_type)
    if coordinator.device_type == APCDeviceType.SMT_UPS:
        await coordinator.async_restore_output_energy_tracker()

    # Load full block polling register profile for detected device type.
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

    await _async_cleanup_stale_entities(hass, entry, coordinator)

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
