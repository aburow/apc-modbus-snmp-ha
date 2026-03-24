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

import asyncio
import functools
import inspect
import logging
import time
from datetime import timedelta
from typing import Any

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .device_types import APCDeviceType, classify_device_type
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
        host: str,
        port: int,
        entry_id: str,
        timeout: int,
        io_lock: asyncio.Lock,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.unit = unit
        self.device_name = device_name
        self.host = host
        self.port = port
        self.entry_id = entry_id
        self.timeout = timeout
        self._log_ctx = f"{self.device_name} {self.host}:{self.port} (unit {self.unit})"
        # Serialize Modbus client access to avoid concurrent reads on one socket.
        self._io_lock = io_lock
        # Connection/backoff tracking
        self._connect_failures = 0
        self._backoff_until: float | None = None
        self._backoff_base = 2.0
        self._backoff_max = 60.0
        # Small pacing delays for devices that drop connections on back-to-back reads.
        # Defaults for Smart-UPS; Rack PDU overrides in set_device_type().
        self._post_connect_delay = 0.05
        self._inter_block_delay = 0.05
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
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._device_kwarg_name = "device_id" if "device_id" in read_params else "slave"

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
        """Store device type and tune pacing for slower models."""
        self.device_type = device_type
        _LOGGER.info("Device type set to: %s", device_type.value)
        # Rack PDU is typically slower to respond, so use longer delays.
        if self.device_type == APCDeviceType.RACK_PDU:
            self._post_connect_delay = 0.10
            self._inter_block_delay = 0.10

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
        _LOGGER.debug(
            "Registers updated: %d registers, %d blocks",
            len(registers),
            len(register_blocks),
        )

    async def async_detect_device_type(self) -> APCDeviceType | None:
        """Probe distinguishing Modbus addresses to identify the device type."""
        async with self._io_lock:
            if not await self._ensure_connection():
                _LOGGER.debug(
                    "[%s] Device probe skipped: unable to connect", self._log_ctx
                )
                return None

            rack_pdu_capabilities_ok = await self._probe_block(
                0x009E, 5, "rack_pdu_capabilities"
            )
            rack_pdu_measurements_ok = await self._probe_block(
                0x00CF, 6, "rack_pdu_measurements"
            )
            legacy_probe_ok = await self._probe_block(0x0021, 1, "legacy_ups_id")
            smt_status_ok = await self._probe_block(0x0000, 23, "smt_status")
            smt_measurements_ok = await self._probe_block(
                0x0080, 26, "smt_measurements"
            )

            detected = classify_device_type(
                rack_pdu_capabilities_ok=rack_pdu_capabilities_ok,
                rack_pdu_measurements_ok=rack_pdu_measurements_ok,
                legacy_probe_ok=legacy_probe_ok,
                smt_status_ok=smt_status_ok,
                smt_measurements_ok=smt_measurements_ok,
            )

            _LOGGER.debug(
                "[%s] Device probe results: pdu_caps=%s pdu_measurements=%s legacy=%s smt_status=%s smt_measurements=%s detected=%s",
                self._log_ctx,
                rack_pdu_capabilities_ok,
                rack_pdu_measurements_ok,
                legacy_probe_ok,
                smt_status_ok,
                smt_measurements_ok,
                detected.value if detected else "ambiguous",
            )
            return detected

    async def _probe_block(self, address: int, count: int, probe_name: str) -> bool:
        """Return True when a probe read succeeds with a non-error response."""
        try:
            if self._inter_block_delay > 0:
                await asyncio.sleep(self._inter_block_delay)
            read_request = self._build_read_request(address, count)
            result = await self.hass.async_add_executor_job(read_request)
            ok = not self._is_error_response(result)
            _LOGGER.debug(
                "[%s] Probe %s at 0x%04X count=%d -> %s",
                self._log_ctx,
                probe_name,
                address,
                count,
                ok,
            )
            return ok
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.debug(
                "[%s] Probe %s at 0x%04X count=%d failed: %s",
                self._log_ctx,
                probe_name,
                address,
                count,
                err,
            )
            return False

    def _build_read_request(self, address: int, count: int):
        """Build a compatible read request for old and new pymodbus APIs."""
        return functools.partial(
            self.client.read_holding_registers,
            address,
            count=count,
            **{self._device_kwarg_name: self.unit},
        )

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
            async with self._io_lock:
                for cap_name, addr in capability_regs.items():
                    try:
                        read_request = self._build_read_request(addr, 1)
                        result = await self.hass.async_add_executor_job(read_request)

                        if not self._is_error_response(result) and result.registers:
                            capabilities[cap_name] = result.registers[0]
                        else:
                            _LOGGER.debug(
                                "Failed to read capability register %s at 0x%04X",
                                cap_name,
                                addr,
                            )
                    except (
                        ConnectionException,
                        ModbusException,
                        OSError,
                        TimeoutError,
                    ) as err:
                        _LOGGER.debug(
                            "Error reading capability register %s: %s", cap_name, err
                        )

            if capabilities:
                _LOGGER.info(
                    "Rack PDU capabilities discovered: %d phases, %d outlets, %d banks",
                    capabilities.get("num_phases", 0),
                    capabilities.get("num_metered_outlets", 0),
                    capabilities.get("num_banks", 0),
                )
            else:
                _LOGGER.warning(
                    "Failed to discover any capability registers for Rack PDU"
                )

        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.error("Error discovering capabilities: %s", err)

        return capabilities

    @staticmethod
    def _is_error_response(result) -> bool:
        """Check if a Modbus response indicates an error (pymodbus 3.6+ compatible)."""
        # For pymodbus 3.6+: Check if registers attribute exists and is not None
        if not hasattr(result, "registers"):
            return True
        if result.registers is None:
            return True
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the UPS via Modbus (block reads with fallback to individual reads)."""
        data: dict[str, Any] = {}
        errors: list[str] = []

        _LOGGER.debug(
            "[%s] Starting update cycle (entry_id=%s)", self._log_ctx, self.entry_id
        )

        # Serialize all client I/O to avoid concurrent Modbus socket use.
        lock_wait_start = time.monotonic()
        async with self._io_lock:
            lock_wait = time.monotonic() - lock_wait_start
            if lock_wait > 0:
                _LOGGER.debug(
                    "[%s] Waited %.3fs for I/O lock", self._log_ctx, lock_wait
                )
            cycle_start = time.monotonic()
            _LOGGER.debug("[%s] Acquired I/O lock", self._log_ctx)
            try:
                if not self._should_run_now():
                    raise UpdateFailed("Backoff active; skipping update cycle")
                if not await self._ensure_connection():
                    raise UpdateFailed("Unable to connect to APC UPS")
                # Try block reads first (optimized) with reconnection logic
                _LOGGER.debug("[%s] Attempting block reads", self._log_ctx)
                block_read_ok = await self._try_block_reads(data, errors)
                _LOGGER.debug(
                    "[%s] Block reads result: %s (data keys: %s)",
                    self._log_ctx,
                    "success" if block_read_ok else "failed",
                    list(data.keys()),
                )

                # If block reads failed, fall back to individual reads with reconnection
                if not block_read_ok:
                    _LOGGER.info(
                        "[%s] Block reads failed or incomplete, falling back to individual register reads",
                        self._log_ctx,
                    )
                    # Don't clear data - preserve any partial data from successful block reads
                    await self._try_individual_reads(data, errors)
                    _LOGGER.debug(
                        "[%s] Individual reads fallback complete (data keys: %s)",
                        self._log_ctx,
                        list(data.keys()),
                    )
                    _LOGGER.debug(
                        "[%s] Individual reads fallback complete (data keys: %s)",
                        self._log_ctx,
                        list(data.keys()),
                    )
            except UpdateFailed as err:
                self._register_failure(str(err))
                raise
            except Exception as err:
                self._register_failure(str(err))
                raise
            finally:
                # Close per-cycle to avoid stale sockets on devices that drop idle connections.
                close_start = time.monotonic()
                try:
                    close_request = functools.partial(self.client.close)
                    await self.hass.async_add_executor_job(close_request)
                    _LOGGER.debug(
                        "[%s] Closed Modbus client after update (%.3fs)",
                        self._log_ctx,
                        time.monotonic() - close_start,
                    )
                except (
                    ConnectionException,
                    ModbusException,
                    OSError,
                    TimeoutError,
                ) as close_err:
                    _LOGGER.debug(
                        "[%s] Error closing Modbus client: %s", self._log_ctx, close_err
                    )

        if not data:
            self._register_failure("No data read")
            raise UpdateFailed(f"Unable to read any registers: {', '.join(errors)}")

        if errors:
            _LOGGER.debug(
                "[%s] Failed to read %d registers: %s",
                self._log_ctx,
                len(errors),
                ", ".join(errors),
            )

        # Log successful data keys for debugging
        _LOGGER.debug(
            "[%s] Successfully read %d registers: %s",
            self._log_ctx,
            len(data),
            ", ".join(sorted(data.keys())),
        )
        _LOGGER.debug(
            "[%s] Update cycle complete in %.3fs",
            self._log_ctx,
            time.monotonic() - cycle_start,
        )
        self._reset_backoff()

        return data

    async def _ensure_connection(self) -> bool:
        """Ensure Modbus client is connected before starting reads."""
        try:
            connect_start = time.monotonic()
            connect_request = functools.partial(self.client.connect)
            ok = await self.hass.async_add_executor_job(connect_request)
            _LOGGER.debug(
                "[%s] client.connect() -> %s (%.3fs)",
                self._log_ctx,
                ok,
                time.monotonic() - connect_start,
            )
            if ok:
                self._connect_failures = 0
                if self._post_connect_delay > 0:
                    await asyncio.sleep(self._post_connect_delay)
                    _LOGGER.debug(
                        "[%s] Post-connect delay %.3fs",
                        self._log_ctx,
                        self._post_connect_delay,
                    )
                return True
            self._connect_failures += 1
            if self._connect_failures >= 3:
                _LOGGER.debug(
                    "[%s] Recreating Modbus client after %d connect failures",
                    self._log_ctx,
                    self._connect_failures,
                )
                await self._recreate_client()
                self._connect_failures = 0
                reconnect_start = time.monotonic()
                reconnect_request = functools.partial(self.client.connect)
                ok = await self.hass.async_add_executor_job(reconnect_request)
                _LOGGER.debug(
                    "[%s] client.connect() after recreate -> %s (%.3fs)",
                    self._log_ctx,
                    ok,
                    time.monotonic() - reconnect_start,
                )
                return ok
            return False
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.debug("[%s] Connection attempt failed: %s", self._log_ctx, err)
            return False

    async def _recreate_client(self) -> None:
        """Close and recreate the Modbus client to clear dead sockets."""
        try:
            close_request = functools.partial(self.client.close)
            await self.hass.async_add_executor_job(close_request)
        except (ConnectionException, ModbusException, OSError, TimeoutError):
            pass
        self.client = ModbusTcpClient(
            host=self.host, port=self.port, timeout=self.timeout
        )

    def _register_failure(self, reason: str) -> None:
        """Apply exponential backoff on repeated failures."""
        now = time.monotonic()
        prev = self._backoff_until or now
        if prev < now:
            self._backoff_until = now + self._backoff_base
        else:
            delay = min(self._backoff_max, (prev - now) * self._backoff_base)
            self._backoff_until = now + delay
        if self._backoff_until:
            _LOGGER.debug(
                "[%s] Backoff set for %.1fs due to failure: %s",
                self._log_ctx,
                self._backoff_until - now,
                reason,
            )

    def _reset_backoff(self) -> None:
        self._backoff_until = None

    def _should_run_now(self) -> bool:
        if self._backoff_until is None:
            return True
        return time.monotonic() >= self._backoff_until

    async def _try_block_reads(self, data: dict[str, Any], errors: list[str]) -> bool:
        """Try to read data using block reads. Returns True if any blocks succeed, False if all fail."""
        block_success_count = 0

        for block in self.register_blocks:
            try:
                if self._inter_block_delay > 0:
                    await asyncio.sleep(self._inter_block_delay)
                block_start = time.monotonic()
                _LOGGER.debug(
                    "[%s] Reading block %s (addr 0x%04X, count %d)",
                    self._log_ctx,
                    block["name"],
                    block["start_address"],
                    block["count"],
                )
                read_request = self._build_read_request(
                    block["start_address"], block["count"]
                )
                result = await self.hass.async_add_executor_job(read_request)

                # Check if result is an error
                if self._is_error_response(result):
                    _LOGGER.warning(
                        "[%s] Block read returned error %s (0x%04X, %d registers): %s",
                        self._log_ctx,
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
                _LOGGER.debug(
                    "[%s] Block read succeeded: %s (%.3fs)",
                    self._log_ctx,
                    block["name"],
                    time.monotonic() - block_start,
                )
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
                    except (TypeError, ValueError, KeyError, IndexError) as err:
                        errors.append(descriptor["key"])
                        _LOGGER.debug(
                            "Error decoding register %s: %s",
                            descriptor["key"],
                            err,
                        )

            except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
                _LOGGER.warning(
                    "[%s] Exception in block read %s: %s (type: %s)",
                    self._log_ctx,
                    block["name"],
                    err,
                    type(err).__name__,
                )

                # Try to reconnect on connection errors (same as individual reads)
                err_str = str(err).lower()
                if (
                    "broken pipe" in err_str
                    or "connection" in err_str
                    or "reset" in err_str
                ):
                    _LOGGER.debug(
                        "[%s] Connection error in block read, attempting to reconnect and retry",
                        self._log_ctx,
                    )
                    try:
                        # Close existing connection
                        close_request = functools.partial(self.client.close)
                        await self.hass.async_add_executor_job(close_request)

                        # Recreate client on broken pipe / connection reset
                        if "broken pipe" in err_str or "reset" in err_str:
                            _LOGGER.debug(
                                "[%s] Recreating Modbus client after socket error",
                                self._log_ctx,
                            )
                            await self._recreate_client()

                        # Reconnect
                        connect_request = functools.partial(self.client.connect)
                        await self.hass.async_add_executor_job(connect_request)

                        # Retry the block read
                        read_request = self._build_read_request(
                            block["start_address"], block["count"]
                        )
                        result = await self.hass.async_add_executor_job(read_request)

                        if not self._is_error_response(result):
                            _LOGGER.debug(
                                "[%s] Block read succeeded after reconnect: %s (%.3fs)",
                                self._log_ctx,
                                block["name"],
                                time.monotonic() - block_start,
                            )
                            block_success_count += 1
                            # Decode the registers from this successful block
                            for addr in block["registers"]:
                                if addr not in self.register_map:
                                    continue

                                descriptor = self.register_map[addr]
                                offset = addr - block["start_address"]
                                reg_count = descriptor["count"]
                                reg_slice = result.registers[
                                    offset : offset + reg_count
                                ]

                                if len(reg_slice) < reg_count:
                                    errors.append(descriptor["key"])
                                    continue

                                try:
                                    value = self._decode_register(reg_slice, descriptor)
                                    if value is not None:
                                        data[descriptor["key"]] = value
                                except (
                                    TypeError,
                                    ValueError,
                                    KeyError,
                                    IndexError,
                                ) as decode_err:
                                    errors.append(descriptor["key"])
                                    _LOGGER.debug(
                                        "Error decoding register %s: %s",
                                        descriptor["key"],
                                        decode_err,
                                    )
                            continue  # Skip the error marking below
                    except (
                        ConnectionException,
                        ModbusException,
                        OSError,
                        TimeoutError,
                    ) as reconnect_err:
                        _LOGGER.debug(
                            "[%s] Failed to reconnect and retry block: %s",
                            self._log_ctx,
                            reconnect_err,
                        )

                # Mark all registers in this block as failed
                for addr in block["registers"]:
                    if addr in self.register_map:
                        errors.append(self.register_map[addr]["key"])

        # Return True if at least one block succeeded
        return block_success_count > 0

    async def _try_individual_reads(
        self, data: dict[str, Any], errors: list[str]
    ) -> None:
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
                        _LOGGER.warning(
                            "[%s] Too many consecutive read failures, aborting update cycle",
                            self._log_ctx,
                        )
                        break
                    continue

                # Reset failure counter on successful read
                consecutive_failures = 0

                # Check if result is an error
                if self._is_error_response(result):
                    errors.append(descriptor["key"])
                    _LOGGER.debug(
                        "[%s] Failed to read register %s (address 0x%04X): %s",
                        self._log_ctx,
                        descriptor["key"],
                        descriptor["address"],
                        result,
                    )
                    continue

                value = self._decode_register(result.registers, descriptor)
                if value is not None:
                    data[descriptor["key"]] = value
            except (
                ConnectionException,
                ModbusException,
                OSError,
                TimeoutError,
                TypeError,
                ValueError,
                KeyError,
                IndexError,
            ) as err:
                errors.append(descriptor["key"])
                consecutive_failures += 1
                _LOGGER.debug(
                    "[%s] Exception reading register %s (address 0x%04X): %s",
                    self._log_ctx,
                    descriptor["key"],
                    descriptor["address"],
                    err,
                )

                if consecutive_failures >= 5:
                    _LOGGER.warning(
                        "[%s] Too many consecutive read failures, aborting update cycle",
                        self._log_ctx,
                    )
                    break

    async def _read_register_with_reconnect(self, descriptor: dict[str, Any]):
        """Read a register with automatic reconnection on failure."""
        # Attempt read with current connection
        try:
            read_request = self._build_read_request(
                descriptor["address"], descriptor["count"]
            )
            result = await self.hass.async_add_executor_job(read_request)
            return result
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            # Connection likely dropped, attempt to reconnect and retry
            err_str = str(err).lower()
            _LOGGER.debug(
                "[%s] Read error for %s (address 0x%04X): %s (type: %s)",
                self._log_ctx,
                descriptor["key"],
                descriptor["address"],
                err,
                type(err).__name__,
            )

            if (
                "broken pipe" in err_str
                or "connection" in err_str
                or "reset" in err_str
            ):
                _LOGGER.debug(
                    "[%s] Connection error detected, attempting reconnect for %s",
                    self._log_ctx,
                    descriptor["key"],
                )

                try:
                    # Close existing connection
                    close_request = functools.partial(self.client.close)
                    await self.hass.async_add_executor_job(close_request)
                except (ConnectionException, ModbusException, OSError, TimeoutError):
                    pass  # Ignore close errors

                try:
                    if "broken pipe" in err_str or "reset" in err_str:
                        _LOGGER.debug(
                            "[%s] Recreating Modbus client after socket error",
                            self._log_ctx,
                        )
                        await self._recreate_client()
                    # Reconnect
                    connect_request = functools.partial(self.client.connect)
                    await self.hass.async_add_executor_job(connect_request)

                    # Retry the read
                    read_request = self._build_read_request(
                        descriptor["address"], descriptor["count"]
                    )
                    result = await self.hass.async_add_executor_job(read_request)
                    _LOGGER.debug(
                        "[%s] Successfully reconnected and read register %s",
                        self._log_ctx,
                        descriptor["key"],
                    )
                    return result
                except (
                    ConnectionException,
                    ModbusException,
                    OSError,
                    TimeoutError,
                ) as reconnect_err:
                    _LOGGER.debug(
                        "[%s] Failed to reconnect and read register %s: %s",
                        self._log_ctx,
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
