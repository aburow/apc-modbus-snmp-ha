# SPDX-License-Identifier: GPL-3.0
# Copyright (C) 2026 Anthony Burow
# https://github.com/aburow/apc-modbus-snmp-ha

"""Modbus data coordinator for APC UPS sensors.

Note: pymodbus API compatibility
- pymodbus 2.x: result.isError() (camelCase)
- pymodbus 3.0-3.5: result.is_error() (snake_case)
- pymodbus 3.6+: Check hasattr(result, 'registers') instead
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from pymodbus.client import ModbusTcpClient
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL
from .device_types import APCDeviceType
from . import registers_smart_ups

_LOGGER = logging.getLogger(__name__)


class APCModbusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls Modbus registers for the UPS."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ModbusTcpClient,
        unit: int,
        device_name: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = client
        self.unit = unit
        self.device_name = device_name
        # Initialize data as empty dict to ensure it's always present
        self.data: dict[str, Any] = {}
        # Device metadata (populated via SNMP at startup)
        self.hw_model: str | None = None
        self.serial_number: str | None = None
        self.fw_version: str | None = None
        self.fw_date: str | None = None
        # Device type and capabilities (for multi-device support)
        self.device_type: APCDeviceType = APCDeviceType.SMART_UPS
        self.device_capabilities: dict[str, int] = {}
        # Registers and blocks (loaded from factory based on device type)
        self.registers: list[dict[str, Any]] = registers_smart_ups.REGISTERS
        self.register_blocks: list[dict[str, Any]] = registers_smart_ups.REGISTER_BLOCKS
        self.register_map: dict[int, dict[str, Any]] = registers_smart_ups.REGISTER_MAP

    def set_device_metadata(
        self,
        hw_model: str | None,
        serial_number: str | None,
        fw_version: str | None,
        fw_date: str | None,
    ) -> None:
        """Set device metadata from SNMP query."""
        self.hw_model = hw_model
        self.serial_number = serial_number
        self.fw_version = fw_version
        self.fw_date = fw_date
        _LOGGER.debug(
            "Device metadata set: model=%s, serial=%s, firmware=%s",
            hw_model,
            serial_number,
            fw_version,
        )

    def set_device_type(self, device_type: APCDeviceType) -> None:
        """Set the detected device type."""
        self.device_type = device_type
        _LOGGER.info("Device type set to: %s", device_type.value)

    def set_capabilities(self, capabilities: dict[str, int]) -> None:
        """Set device capabilities for dynamic entity generation (Rack PDU)."""
        self.device_capabilities = capabilities
        _LOGGER.debug("Device capabilities set: %s", capabilities)

    def set_registers(
        self,
        registers: list[dict[str, Any]],
        register_blocks: list[dict[str, Any]],
        register_map: dict[int, dict[str, Any]],
    ) -> None:
        """Set registers, blocks, and map for the device type."""
        self.registers = registers
        self.register_blocks = register_blocks
        self.register_map = register_map
        _LOGGER.debug("Registers updated: %d registers, %d blocks", len(registers), len(register_blocks))

    async def async_discover_capabilities(self) -> dict[str, int]:
        """Discover device capabilities for Rack PDU (reads capability registers).

        Returns a dict with keys: num_phases, num_metered_phases, num_banks, num_outlets, num_metered_outlets
        """
        capabilities = {}

        # Capability register addresses
        capability_regs = {
            "num_phases": 0x009E,
            "num_metered_phases": 0x009F,
            "num_banks": 0x00A0,
            "num_outlets": 0x00A1,
            "num_metered_outlets": 0x00A2,
        }

        try:
            # Try to read capability registers
            for cap_name, addr in capability_regs.items():
                try:
                    read_request = functools.partial(
                        self.client.read_holding_registers,
                        addr,
                        count=1,
                        device_id=self.unit,
                    )
                    result = await self.hass.async_add_executor_job(read_request)

                    if not self._is_error_response(result) and result.registers:
                        capabilities[cap_name] = result.registers[0]
                    else:
                        _LOGGER.debug("Failed to read capability register %s at 0x%04X", cap_name, addr)
                except Exception as err:
                    _LOGGER.debug("Error reading capability register %s: %s", cap_name, err)

            if capabilities:
                _LOGGER.info(
                    "Rack PDU capabilities discovered: %d phases, %d outlets, %d banks",
                    capabilities.get("num_phases", 0),
                    capabilities.get("num_metered_outlets", 0),
                    capabilities.get("num_banks", 0),
                )
            else:
                _LOGGER.warning("Failed to discover any capability registers for Rack PDU")

        except Exception as err:
            _LOGGER.error("Error discovering capabilities: %s", err)

        return capabilities

    @staticmethod
    def _is_error_response(result) -> bool:
        """Check if a Modbus response indicates an error (pymodbus 3.6+ compatible)."""
        # For pymodbus 3.6+: Check if registers attribute exists and is not None
        if not hasattr(result, 'registers'):
            return True
        if result.registers is None:
            return True
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the UPS via Modbus (block reads with fallback to individual reads)."""
        data: dict[str, Any] = {}
        errors: list[str] = []

        _LOGGER.debug("Starting update cycle")

        # Try block reads first (optimized) with reconnection logic
        _LOGGER.debug("Attempting block reads")
        block_read_ok = await self._try_block_reads(data, errors)
        _LOGGER.debug("Block reads result: %s (data keys: %s)", "success" if block_read_ok else "failed", list(data.keys()))

        # If block reads failed, fall back to individual reads with reconnection
        if not block_read_ok:
            _LOGGER.info("Block reads failed or incomplete, falling back to individual register reads")
            # Don't clear data - preserve any partial data from successful block reads
            await self._try_individual_reads(data, errors)
            _LOGGER.debug("Individual reads fallback complete (data keys: %s)", list(data.keys()))
            _LOGGER.debug("Individual reads fallback complete (data keys: %s)", list(data.keys()))

        if not data:
            raise UpdateFailed(f"Unable to read any registers: {', '.join(errors)}")

        if errors:
            _LOGGER.debug("Failed to read %d registers: %s", len(errors), ", ".join(errors))

        # Log successful data keys for debugging
        _LOGGER.debug("Successfully read %d registers: %s", len(data), ", ".join(sorted(data.keys())))

        return data

    async def _try_block_reads(self, data: dict[str, Any], errors: list[str]) -> bool:
        """Try to read data using block reads. Returns True if any blocks succeed, False if all fail."""
        block_success_count = 0

        for block in self.register_blocks:
            try:
                _LOGGER.debug("Reading block %s (addr 0x%04X, count %d)", block["name"], block["start_address"], block["count"])
                read_request = functools.partial(
                    self.client.read_holding_registers,
                    block["start_address"],
                    count=block["count"],
                    device_id=self.unit,
                )
                result = await self.hass.async_add_executor_job(read_request)

                # Check if result is an error
                if self._is_error_response(result):
                    _LOGGER.warning(
                        "Block read returned error %s (0x%04X, %d registers): %s",
                        block["name"],
                        block["start_address"],
                        block["count"],
                        result,
                    )
                    # Mark all registers in this block as failed, but continue to next block
                    for addr in block["registers"]:
                        if addr in self.register_map:
                            errors.append(self.register_map[addr]["key"])
                    continue

                # Block read successful, increment counter
                _LOGGER.debug("Block read succeeded: %s", block["name"])
                block_success_count += 1

                # Decode each register in the block
                for addr in block["registers"]:
                    if addr not in self.register_map:
                        continue

                    descriptor = self.register_map[addr]
                    offset = addr - block["start_address"]
                    reg_count = descriptor["count"]
                    reg_slice = result.registers[offset : offset + reg_count]

                    if len(reg_slice) < reg_count:
                        _LOGGER.debug(
                            "Insufficient registers for %s at offset %d",
                            descriptor["key"],
                            offset,
                        )
                        errors.append(descriptor["key"])
                        continue

                    try:
                        value = self._decode_register(reg_slice, descriptor)
                        if value is not None:
                            data[descriptor["key"]] = value
                    except Exception as err:
                        errors.append(descriptor["key"])
                        _LOGGER.debug(
                            "Error decoding register %s: %s",
                            descriptor["key"],
                            err,
                        )

            except Exception as err:
                _LOGGER.warning("Exception in block read %s: %s (type: %s)", block["name"], err, type(err).__name__)

                # Try to reconnect on connection errors (same as individual reads)
                err_str = str(err).lower()
                if "broken pipe" in err_str or "connection" in err_str or "reset" in err_str:
                    _LOGGER.debug("Connection error in block read, attempting to reconnect and retry")
                    try:
                        # Close existing connection
                        close_request = functools.partial(self.client.close)
                        await self.hass.async_add_executor_job(close_request)

                        # Reconnect
                        connect_request = functools.partial(self.client.connect)
                        await self.hass.async_add_executor_job(connect_request)

                        # Retry the block read
                        read_request = functools.partial(
                            self.client.read_holding_registers,
                            block["start_address"],
                            count=block["count"],
                            device_id=self.unit,
                        )
                        result = await self.hass.async_add_executor_job(read_request)

                        if not self._is_error_response(result):
                            _LOGGER.debug("Block read succeeded after reconnect: %s", block["name"])
                            block_success_count += 1
                            # Decode the registers from this successful block
                            for addr in block["registers"]:
                                if addr not in self.register_map:
                                    continue

                                descriptor = self.register_map[addr]
                                offset = addr - block["start_address"]
                                reg_count = descriptor["count"]
                                reg_slice = result.registers[offset : offset + reg_count]

                                if len(reg_slice) < reg_count:
                                    errors.append(descriptor["key"])
                                    continue

                                try:
                                    value = self._decode_register(reg_slice, descriptor)
                                    if value is not None:
                                        data[descriptor["key"]] = value
                                except Exception as decode_err:
                                    errors.append(descriptor["key"])
                                    _LOGGER.debug("Error decoding register %s: %s", descriptor["key"], decode_err)
                            continue  # Skip the error marking below
                    except Exception as reconnect_err:
                        _LOGGER.debug("Failed to reconnect and retry block: %s", reconnect_err)

                # Mark all registers in this block as failed
                for addr in block["registers"]:
                    if addr in self.register_map:
                        errors.append(self.register_map[addr]["key"])

        # Return True if at least one block succeeded
        return block_success_count > 0

    async def _try_individual_reads(self, data: dict[str, Any], errors: list[str]) -> None:
        """Try to read data using individual registers with reconnection logic."""
        consecutive_failures = 0

        for descriptor in self.registers:
            try:
                # Try to read register with automatic reconnection if needed
                result = await self._read_register_with_reconnect(descriptor)

                if result is None:
                    # Connection error, already logged
                    errors.append(descriptor["key"])
                    consecutive_failures += 1

                    # If too many consecutive failures, abort
                    if consecutive_failures >= 5:
                        _LOGGER.warning("Too many consecutive read failures, aborting update cycle")
                        break
                    continue

                # Reset failure counter on successful read
                consecutive_failures = 0

                # Check if result is an error
                if self._is_error_response(result):
                    errors.append(descriptor["key"])
                    _LOGGER.debug(
                        "Failed to read register %s (address 0x%04X): %s",
                        descriptor["key"],
                        descriptor["address"],
                        result,
                    )
                    continue

                value = self._decode_register(result.registers, descriptor)
                if value is not None:
                    data[descriptor["key"]] = value
            except Exception as err:
                errors.append(descriptor["key"])
                consecutive_failures += 1
                _LOGGER.debug(
                    "Exception reading register %s (address 0x%04X): %s",
                    descriptor["key"],
                    descriptor["address"],
                    err,
                )

                if consecutive_failures >= 5:
                    _LOGGER.warning("Too many consecutive read failures, aborting update cycle")
                    break

    async def _read_register_with_reconnect(self, descriptor: dict[str, Any]):
        """Read a register with automatic reconnection on failure."""
        # Attempt read with current connection
        try:
            read_request = functools.partial(
                self.client.read_holding_registers,
                descriptor["address"],
                count=descriptor["count"],
                device_id=self.unit,
            )
            result = await self.hass.async_add_executor_job(read_request)
            return result
        except Exception as err:
            # Connection likely dropped, attempt to reconnect and retry
            err_str = str(err).lower()
            _LOGGER.debug("Read error for %s (address 0x%04X): %s (type: %s)", descriptor["key"], descriptor["address"], err, type(err).__name__)

            if "broken pipe" in err_str or "connection" in err_str or "reset" in err_str:
                _LOGGER.debug(
                    "Connection error detected, attempting reconnect for %s",
                    descriptor["key"],
                )

                try:
                    # Close existing connection
                    close_request = functools.partial(self.client.close)
                    await self.hass.async_add_executor_job(close_request)
                except Exception:
                    pass  # Ignore close errors

                try:
                    # Reconnect
                    connect_request = functools.partial(self.client.connect)
                    await self.hass.async_add_executor_job(connect_request)

                    # Retry the read
                    read_request = functools.partial(
                        self.client.read_holding_registers,
                        descriptor["address"],
                        count=descriptor["count"],
                        device_id=self.unit,
                    )
                    result = await self.hass.async_add_executor_job(read_request)
                    _LOGGER.debug("Successfully reconnected and read register %s", descriptor["key"])
                    return result
                except Exception as reconnect_err:
                    _LOGGER.debug(
                        "Failed to reconnect and read register %s: %s",
                        descriptor["key"],
                        reconnect_err,
                    )
                    return None
            else:
                # Not a connection error, re-raise
                raise

    def _decode_register(
        self, registers: list[int], descriptor: dict[str, Any]
    ) -> float | int | None:
        """Decode register payloads to a numeric value."""
        dtype = descriptor.get("type")
        scale = descriptor.get("scale", 1)

        raw: int

        if dtype in ("uint16", "int16") and registers:
            raw = registers[0]
            if dtype == "int16" and raw >= 0x8000:
                raw -= 0x10000
        elif dtype in ("uint32", "int32") and len(registers) >= 2:
            raw = (registers[0] << 16) | registers[1]
            if dtype == "int32" and raw >= 0x80000000:
                raw -= 0x100000000
        elif dtype == "ascii" and registers:
            ascii_width = descriptor.get("ascii_width", 2)
            chars: list[str] = []
            for reg in registers:
                if ascii_width == 1:
                    # One char per register: character is in lower byte (LSB)
                    # Upper byte is typically 0x00 padding
                    chars.append(chr(reg & 0xFF))
                else:
                    # Two chars per register: MSB first (big-endian)
                    chars.append(chr((reg >> 8) & 0xFF))
                    chars.append(chr(reg & 0xFF))
            return "".join(chars).rstrip()
        else:
            return None

        if scale and scale != 1:
            return raw / scale

        return raw
