# SPDX-License-Identifier: AGPL-3.0-or-later
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
import logging
import time
from datetime import timedelta
from ipaddress import ip_address
from typing import Any, Callable

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_IDLE_RECONNECT_SECONDS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .device_types import (
    APCDeviceType,
    classify_device_type,
    device_type_label,
    ProbeKind,
    ProbeOutcome,
    SCHEMA_PROBES,
)
from .modbus_poller import ModbusPoller
from .modbus_transport import ModbusTransport
from . import registers_smart_ups
from .snmp_helper import (
    detect_external_probe_oids_sync,
    get_device_metadata_sync,
    get_external_probe_data_detected_sync,
    get_self_test_data_sync,
)
from .snmp_state import has_usable_metadata

_LOGGER = logging.getLogger(__name__)
METADATA_REFRESH_INTERVAL_SECONDS = 3600
SELF_TEST_REFRESH_INTERVAL_SECONDS = 60
OUTPUT_ENERGY_STORE_SAVE_DELAY_SECONDS = 60


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
        snmp_community: str,
        snmp_port: int,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        keep_connection_open: bool = False,
        transport_mode: str = "session",
        transport_mode_persist: Callable[[str], None] | None = None,
        output_energy_completed_rollovers: int = 0,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.unit = unit
        self.device_name = device_name
        self.host = host
        self.port = port
        self.entry_id = entry_id
        self.timeout = timeout
        self.snmp_community = snmp_community
        self.snmp_port = snmp_port
        self._keep_connection_open = keep_connection_open
        self._transport_mode_persist = transport_mode_persist
        self._idle_reconnect_seconds = DEFAULT_IDLE_RECONNECT_SECONDS
        self._log_ctx = f"{self.device_name} {self.host}:{self.port} (unit {self.unit})"
        self._io_lock = io_lock
        self._backoff_until: float | None = None
        self._backoff_base = 2.0
        self._backoff_max = 60.0
        self._modbus_failure_started: float | None = None
        self._modbus_failure_warning_emitted = False
        self._inter_block_delay = 0.05
        self._transport = ModbusTransport(
            hass,
            client,
            unit,
            host,
            port,
            timeout,
            io_lock,
            self._log_ctx,
            transport_mode,
            transport_mode_persist,
            lambda: self.effective_keep_connection_open,
            self._idle_reconnect_seconds,
        )
        # Initialize data as empty dict to ensure it's always present
        self.data: dict[str, Any] = {}
        # Device metadata (populated via SNMP at startup)
        self.hw_model: str | None = None
        self.serial_number: str | None = None
        self.fw_version: str | None = None
        self.fw_date: str | None = None
        self._metadata_needs_refresh = True
        self._metadata_last_refresh_monotonic = 0.0
        self.snmp_availability = "unknown"
        self.snmp_failure_category: str | None = None
        # External-probe availability/OID selection, refreshed during hourly SNMP metadata poll.
        self._snmp_probe_detection: dict[str, str | None] = {}
        self._snmp_self_test_data: dict[str, Any] = {}
        self._self_test_last_refresh_monotonic = 0.0
        # Device type and capabilities (for multi-device support)
        self.device_type: APCDeviceType = APCDeviceType.SMART_UPS
        self.device_capabilities: dict[str, int] = {}
        self.raw_modbus_model: str | None = None
        self.raw_modbus_sku: str | None = None
        self.raw_modbus_firmware: str | None = None
        # Registers and blocks (loaded from factory based on device type)
        self.registers: list[dict[str, Any]] = registers_smart_ups.REGISTERS
        self.register_blocks: list[dict[str, Any]] = registers_smart_ups.REGISTER_BLOCKS
        self.register_map: dict[int, dict[str, Any]] = registers_smart_ups.REGISTER_MAP
        self._output_energy_completed_rollovers = output_energy_completed_rollovers
        self._poller = ModbusPoller(
            hass,
            self._transport,
            entry_id,
            self._log_ctx,
            output_energy_completed_rollovers,
        )
        self._poller.set_registers(
            self.registers, self.register_blocks, self.register_map
        )

    @property
    def client(self) -> ModbusTcpClient:
        """Compatibility view of the transport-owned client."""
        return self._transport.client

    @property
    def transport(self) -> ModbusTransport:
        """Expose the V2 transport seam to entity platforms."""
        return self._transport

    @property
    def transport_mode(self) -> str:
        return self._transport.mode

    @transport_mode.setter
    def transport_mode(self, value: str) -> None:
        self._transport.mode = value

    @property
    def transport_promotion_reason(self) -> str | None:
        return self._transport.promotion_reason

    @transport_promotion_reason.setter
    def transport_promotion_reason(self, value: str | None) -> None:
        self._transport.promotion_reason = value

    def _transport_value(name: str):
        return property(
            lambda self: getattr(self._transport, name),
            lambda self, value: setattr(self._transport, name, value),
        )

    _connect_failures = _transport_value("connect_failures")
    _last_io_monotonic = _transport_value("last_io_monotonic")
    _reconnect_count = _transport_value("reconnect_count")
    _recreate_count = _transport_value("recreate_count")
    _post_connect_delay = _transport_value("post_connect_delay")
    _min_reconnect_delay = _transport_value("min_reconnect_delay")
    _last_close_monotonic = _transport_value("last_close_monotonic")
    _session_request_succeeded = _transport_value("session_request_succeeded")

    async def async_restore_output_energy_tracker(self) -> None:
        """Restore the SMT output-energy tracker before its first update."""
        await self._poller.async_restore_output_energy_tracker(
            self._output_energy_completed_rollovers
        )

    async def _async_track_output_energy(self, data: dict[str, Any]) -> None:
        """Keep the SMT-compatible output-energy counter in canonical Wh."""
        await self._poller.async_track_output_energy(
            data,
            self.device_type,
            self.serial_number,
            self._output_energy_completed_rollovers,
        )

    def set_device_metadata(
        self,
        hw_model: str | None,
        serial_number: str | None,
        fw_version: str | None,
        fw_date: str | None,
        *,
        mark_refresh_complete: bool = True,
    ) -> None:
        """Set device metadata from SNMP query."""
        self.hw_model = self._clean_metadata_value(hw_model)
        self.serial_number = self._clean_metadata_value(serial_number)
        self.fw_version = self._clean_metadata_value(fw_version)
        self.fw_date = self._clean_metadata_value(fw_date)
        if mark_refresh_complete:
            self._metadata_needs_refresh = False
            self._metadata_last_refresh_monotonic = time.monotonic()
        _LOGGER.debug(
            "Device metadata set: model=%s, serial=%s, firmware=%s",
            self.hw_model,
            self.serial_number,
            self.fw_version,
        )

    def set_snmp_availability(self, available: bool, reason: str | None = None) -> None:
        """Record whether routine SNMP enrichment is safe for this entry."""
        self.snmp_availability = "available" if available else "unavailable"
        self.snmp_failure_category = None if available else reason or "no_metadata"
        if not available:
            self._snmp_probe_detection = {}

    @staticmethod
    def _clean_metadata_value(value: Any) -> str | None:
        """Normalize metadata value to a meaningful string."""
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if normalized.lower() in {
            "unknown",
            "unavailable",
            "n/a",
            "na",
            "none",
            "null",
        }:
            return None
        return normalized

    def set_device_type(self, device_type: APCDeviceType) -> None:
        """Store device type and tune pacing for slower models."""
        changed = self.device_type != device_type
        self.device_type = device_type
        if changed:
            _LOGGER.info(
                "[%s] Device classification set to %s.",
                self._log_ctx,
                device_type_label(device_type),
            )
        # Rack PDU is typically slower to respond, so use longer delays.
        if self.device_type == APCDeviceType.RACK_PDU:
            self._post_connect_delay = 0.10
            self._inter_block_delay = 0.10
        # SmartConnect UPS firmware briefly refuses new TCP connections right
        # after a previous connection closes; diagnosed at 2s (debug-tool
        # POST_PACING_DELAY_SECONDS). Applies whether reconnecting a
        # persistent session or opening a fresh connection per request.
        elif self.device_type == APCDeviceType.SMARTCONNECT_UPS:
            self._min_reconnect_delay = 2.0

    def get_device_model_for_registry(self) -> str:
        """Return the best available model string for Home Assistant device info."""
        if self.hw_model:
            return self.hw_model
        if self.device_type == APCDeviceType.RACK_PDU:
            return "Rack PDU"
        if self.device_type in (APCDeviceType.SMART_UPS, APCDeviceType.SMT_UPS):
            return "Smart-UPS"
        if self.device_type == APCDeviceType.SMARTCONNECT_UPS:
            return "SmartConnect UPS"
        return "APC Device"

    def get_configuration_url_for_registry(self) -> str:
        """Return a best-effort management URL for Home Assistant device info."""
        if self.device_type == APCDeviceType.SMARTCONNECT_UPS:
            return "https://smartconnect.apc.com/dashboard"
        host = (self.host or "").strip()
        if not host:
            return ""
        try:
            if ip_address(host).version == 6:
                return f"http://[{host}]"
        except ValueError:
            pass
        return f"http://{host}"

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
        self._poller.set_registers(registers, register_blocks, register_map)
        _LOGGER.debug(
            "Registers updated: %d registers, %d blocks",
            len(registers),
            len(register_blocks),
        )

    async def async_read_modbus_metadata(self) -> bool:
        """Populate UPS identity from Modbus when SNMP is unavailable."""
        if self.device_type not in (
            APCDeviceType.SMT_UPS,
            APCDeviceType.SMARTCONNECT_UPS,
        ):
            return False

        async with self._io_lock:
            if not await self._ensure_connection():
                return False
            try:
                result = await self.hass.async_add_executor_job(
                    self._build_read_request(0x0204, 56)
                )
            except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
                _LOGGER.debug(
                    "[%s] Modbus metadata read failed: %s", self._log_ctx, err
                )
                return False

        registers = getattr(result, "registers", []) or []
        if self._is_error_response(result) or len(registers) != 56:
            return False

        def decode_ascii(offset: int, count: int) -> str:
            return (
                self._decode_register(
                    registers[offset : offset + count], {"type": "ascii"}
                )
                or ""
            )

        # FW 0x0204, model 0x0214, SKU 0x0224, serial 0x0234.
        firmware = decode_ascii(0, 8)
        model = decode_ascii(16, 16)
        sku = decode_ascii(32, 16)
        serial_number = decode_ascii(48, 8)
        if not any((firmware, model, serial_number)):
            return False

        self.raw_modbus_firmware = self._clean_metadata_value(firmware)
        self.raw_modbus_model = self._clean_metadata_value(model)
        self.raw_modbus_sku = self._clean_metadata_value(sku)

        if self.snmp_availability != "unavailable":
            return True
        self.set_device_metadata(
            hw_model=f"{model} ({sku})" if model and sku else model or sku,
            serial_number=serial_number,
            fw_version=firmware,
            fw_date=None,
            mark_refresh_complete=False,
        )
        return True

    async def async_detect_device_type(self) -> APCDeviceType | None:
        """Probe distinguishing Modbus addresses to identify the device type."""
        async with self._io_lock:
            if not await self._ensure_connection():
                _LOGGER.debug(
                    "[%s] Device probe skipped: unable to connect", self._log_ctx
                )
                return None

            probes: dict[str, ProbeOutcome] = {}
            for probe in SCHEMA_PROBES:
                probes[probe.name] = await self._probe_outcome(
                    probe.address, probe.count, probe.name
                )
                if self.transport_mode == "one_request_per_connection":
                    for retry_probe in SCHEMA_PROBES:
                        if (
                            probes.get(
                                retry_probe.name, ProbeOutcome(ProbeKind.RESPONSE)
                            ).kind
                            == ProbeKind.TRANSPORT_FAILURE
                        ):
                            probes[retry_probe.name] = await self._probe_outcome(
                                retry_probe.address,
                                retry_probe.count,
                                retry_probe.name,
                            )
            detected = classify_device_type(probes)

            _LOGGER.debug(
                "[%s] Device probe results: %s detected=%s",
                self._log_ctx,
                {name: outcome.kind.value for name, outcome in probes.items()},
                detected.value if detected else "ambiguous",
            )
            return detected

    async def _probe_outcome(
        self, address: int, count: int, probe_name: str
    ) -> ProbeOutcome:
        """Collect semantic Modbus evidence without confusing transport failure."""
        try:
            if self._inter_block_delay > 0:
                await asyncio.sleep(self._inter_block_delay)
            read_request = self._build_read_request(address, count)
            result = await self.hass.async_add_executor_job(read_request)
            registers = getattr(result, "registers", []) or []
            if self._is_error_response(result):
                return ProbeOutcome(
                    ProbeKind.MODBUS_EXCEPTION,
                    exception_code=getattr(result, "exception_code", None),
                )
            ok = len(registers) == count
            _LOGGER.debug(
                "[%s] Probe %s at 0x%04X count=%d -> %s (registers=%d)",
                self._log_ctx,
                probe_name,
                address,
                count,
                ok,
                len(registers),
            )
            if ok and self.transport_mode == "session":
                self._session_request_succeeded = True
            return (
                ProbeOutcome(ProbeKind.RESPONSE, tuple(registers))
                if ok
                else ProbeOutcome(ProbeKind.SHORT_RESPONSE)
            )
        except (
            ConnectionException,
            ModbusException,
            OSError,
            TimeoutError,
            TypeError,
        ) as err:
            _LOGGER.debug(
                "[%s] Probe %s at 0x%04X count=%d failed: %s",
                self._log_ctx,
                probe_name,
                address,
                count,
                err,
            )
            self._promote_transport_mode(type(err).__name__)
            return ProbeOutcome(ProbeKind.TRANSPORT_FAILURE)

    def _promote_transport_mode(self, reason: str) -> None:
        """Persist proven single-request compatibility after a session failure."""
        self._transport.promote(reason)

    def _build_read_request(self, address: int, count: int):
        """Build a compatible read request for old and new pymodbus APIs."""
        if self.transport_mode == "one_request_per_connection":
            return functools.partial(self._transport._read_one_request, address, count)
        return functools.partial(
            self._transport._read_holding_registers, address, count
        )

    def _read_one_request(self, address: int, count: int):
        """Read one block on a fresh socket for constrained APC TCP servers.

        Runs in an executor thread, so pacing uses a blocking sleep rather
        than asyncio.sleep.
        """
        return self._transport._read_one_request(address, count)

    @property
    def effective_keep_connection_open(self) -> bool:
        """Return the runtime connection policy without changing user preference."""
        same_endpoint_entries = sum(
            entry.data.get(CONF_HOST) == self.host
            and entry.data.get(CONF_PORT, DEFAULT_PORT) == self.port
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )
        return (
            self._keep_connection_open
            and self.transport_mode == "session"
            and same_endpoint_entries == 1
        )

    def _read_holding_registers_compat(self, address: int, count: int):
        """Read holding registers across pymodbus API variations.

        Supports unit-id argument names used by different pymodbus branches and
        caches the first successful variant for future reads.
        """
        return self._transport._read_holding_registers(address, count)

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
                                "[%s] Failed to read capability register %s at 0x%04X",
                                self._log_ctx,
                                cap_name,
                                addr,
                            )
                    except (
                        ConnectionException,
                        ModbusException,
                        OSError,
                        TimeoutError,
                        TypeError,
                    ) as err:
                        _LOGGER.debug(
                            "[%s] Error reading capability register %s: %s",
                            self._log_ctx,
                            cap_name,
                            err,
                        )

            if capabilities:
                _LOGGER.info(
                    "[%s] Rack PDU capabilities discovered: %d phases, %d outlets, %d banks.",
                    self._log_ctx,
                    capabilities.get("num_phases", 0),
                    capabilities.get("num_metered_outlets", 0),
                    capabilities.get("num_banks", 0),
                )
            else:
                _LOGGER.warning(
                    "[%s] Rack PDU capability discovery returned no usable registers; using defaults.",
                    self._log_ctx,
                )

        except (
            ConnectionException,
            ModbusException,
            OSError,
            TimeoutError,
            TypeError,
        ) as err:
            _LOGGER.error(
                "[%s] Rack PDU capability discovery failed; using defaults.",
                self._log_ctx,
            )
            _LOGGER.debug("[%s] Rack PDU capability failure: %s", self._log_ctx, err)

        return capabilities

    @staticmethod
    def _is_error_response(result) -> bool:
        """Check if a Modbus response indicates an error (pymodbus 3.6+ compatible)."""
        if hasattr(result, "isError") and callable(result.isError):
            return bool(result.isError())
        if hasattr(result, "is_error") and callable(result.is_error):
            return bool(result.is_error())

        if not hasattr(result, "registers"):
            return True
        if result.registers is None:
            return True
        return False

    async def _async_update_data(self) -> dict[str, Any]:
        """Merge one concrete Modbus poll with optional Home Assistant enrichment."""
        poll_start = time.monotonic()
        reconnects_at_start = self._reconnect_count
        recreates_at_start = self._recreate_count
        try:
            if not self._should_run_now():
                remaining = max(0.0, (self._backoff_until or 0) - time.monotonic())
                raise UpdateFailed(
                    f"Modbus retry backoff active; next attempt in about {remaining:.0f}s"
                )
            result = await self._poller.async_poll(
                keep_connection_open=self.effective_keep_connection_open
            )
            data, errors = result.data, result.errors
        except Exception as err:
            self._register_failure(str(err))
            self._record_modbus_failure(str(err))
            raise
        if not data:
            self._register_failure("No data read")
            self._record_modbus_failure("no usable register data was returned")
            raise UpdateFailed(f"Unable to read any registers: {', '.join(errors)}")
        if errors:
            _LOGGER.debug(
                "[%s] Failed to read %d registers: %s",
                self._log_ctx,
                len(errors),
                ", ".join(errors),
            )
        self._reset_backoff()
        self._record_modbus_recovery()
        snmp_metadata_start = time.monotonic()
        await self._maybe_refresh_snmp_metadata()
        snmp_metadata_elapsed = time.monotonic() - snmp_metadata_start
        self._merge_device_metadata(data)
        snmp_external_start = time.monotonic()
        await self._merge_snmp_external_probe_data(data)
        snmp_external_elapsed = time.monotonic() - snmp_external_start
        await self._merge_snmp_self_test_data(data)
        self._apply_device_compat_aliases(data)
        await self._async_track_output_energy(data)
        _LOGGER.debug(
            "[%s] Poll timing breakdown: total=%.3fs, lock_wait=%.3fs, modbus=%.3fs, "
            "block_reads=%.3fs, individual_reads=%.3fs, close=%.3fs, "
            "snmp_metadata=%.3fs, snmp_external=%.3fs, reconnects=%d, recreates=%d",
            self._log_ctx,
            time.monotonic() - poll_start,
            result.lock_wait,
            result.elapsed,
            result.block_reads_elapsed,
            result.individual_reads_elapsed,
            result.close_elapsed,
            snmp_metadata_elapsed,
            snmp_external_elapsed,
            self._reconnect_count - reconnects_at_start,
            self._recreate_count - recreates_at_start,
        )
        return data

    async def _legacy_async_update_data(self) -> dict[str, Any]:
        """Fetch data from the UPS via Modbus (block reads with fallback to individual reads)."""
        data: dict[str, Any] = {}
        errors: list[str] = []
        poll_start = time.monotonic()
        lock_wait = 0.0
        ensure_connection_elapsed = 0.0
        block_reads_elapsed = 0.0
        individual_reads_elapsed = 0.0
        close_elapsed = 0.0
        modbus_cycle_elapsed = 0.0
        snmp_metadata_elapsed = 0.0
        snmp_external_elapsed = 0.0
        reconnects_at_start = self._reconnect_count
        recreates_at_start = self._recreate_count

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
                    remaining = max(0.0, (self._backoff_until or 0) - time.monotonic())
                    raise UpdateFailed(
                        f"Modbus retry backoff active; next attempt in about {remaining:.0f}s"
                    )
                ensure_connection_start = time.monotonic()
                connected = await self._ensure_connection()
                ensure_connection_elapsed = time.monotonic() - ensure_connection_start
                if not connected:
                    raise UpdateFailed("Unable to connect to APC UPS")
                # Try block reads first (optimized) with reconnection logic
                _LOGGER.debug("[%s] Attempting block reads", self._log_ctx)
                mode_before_reads = self.transport_mode
                block_reads_start = time.monotonic()
                block_read_ok = await self._try_block_reads(data, errors)
                block_reads_elapsed = time.monotonic() - block_reads_start
                _LOGGER.debug(
                    "[%s] Block reads result: %s (data keys: %s)",
                    self._log_ctx,
                    "success" if block_read_ok else "failed",
                    list(data.keys()),
                )

                # A promoted mode invalidates any values read on the failed session.
                if self.transport_mode != mode_before_reads:
                    _LOGGER.debug(
                        "[%s] Retrying update with fresh connections after transport promotion",
                        self._log_ctx,
                    )
                    data.clear()
                    errors.clear()
                    block_read_ok = await self._try_block_reads(data, errors)

                # If block reads failed, fall back to individual reads with reconnection.
                if not block_read_ok:
                    _LOGGER.debug(
                        "[%s] Retrying the same reads using individual Modbus registers",
                        self._log_ctx,
                    )
                    individual_reads_start = time.monotonic()
                    mode_before_individual_reads = self.transport_mode
                    errors.clear()
                    await self._try_individual_reads(data, errors)
                    individual_reads_elapsed = time.monotonic() - individual_reads_start
                    if self.transport_mode != mode_before_individual_reads:
                        _LOGGER.debug(
                            "[%s] Retrying update with fresh connections after individual-read transport promotion",
                            self._log_ctx,
                        )
                        data.clear()
                        errors.clear()
                        block_read_ok = await self._try_block_reads(data, errors)
                        if not block_read_ok:
                            await self._try_individual_reads(data, errors)
                    _LOGGER.debug(
                        "[%s] Individual reads fallback complete (data keys: %s)",
                        self._log_ctx,
                        list(data.keys()),
                    )
            except UpdateFailed as err:
                self._register_failure(str(err))
                self._record_modbus_failure(str(err))
                raise
            except Exception as err:
                self._register_failure(str(err))
                self._record_modbus_failure(str(err))
                raise
            finally:
                if self.effective_keep_connection_open:
                    _LOGGER.debug(
                        "[%s] Leaving Modbus client open after update",
                        self._log_ctx,
                    )
                else:
                    # Legacy safe mode: close per-cycle to avoid stale sockets.
                    close_start = time.monotonic()
                    await self._transport.close()
                    close_elapsed = time.monotonic() - close_start
                    self._last_io_monotonic = 0.0
                    _LOGGER.debug(
                        "[%s] Closed Modbus client after update (%.3fs)",
                        self._log_ctx,
                        close_elapsed,
                    )
                modbus_cycle_elapsed = time.monotonic() - cycle_start

        if not data:
            self._register_failure("No data read")
            self._record_modbus_failure("no usable register data was returned")
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
            modbus_cycle_elapsed,
        )
        self._reset_backoff()
        self._record_modbus_recovery()

        snmp_metadata_start = time.monotonic()
        await self._maybe_refresh_snmp_metadata()
        snmp_metadata_elapsed = time.monotonic() - snmp_metadata_start
        self._merge_device_metadata(data)

        # Merge optional SNMP-backed external probe values.
        snmp_external_start = time.monotonic()
        await self._merge_snmp_external_probe_data(data)
        snmp_external_elapsed = time.monotonic() - snmp_external_start

        await self._merge_snmp_self_test_data(data)
        self._apply_device_compat_aliases(data)
        await self._async_track_output_energy(data)
        self._clear_reconciled_unknown_writes(data)

        _LOGGER.debug(
            "[%s] Poll timing breakdown: total=%.3fs, lock_wait=%.3fs, modbus=%.3fs, "
            "connect=%.3fs, block_reads=%.3fs, individual_reads=%.3fs, close=%.3fs, "
            "snmp_metadata=%.3fs, snmp_external=%.3fs, reconnects=%d, recreates=%d",
            self._log_ctx,
            time.monotonic() - poll_start,
            lock_wait,
            modbus_cycle_elapsed,
            ensure_connection_elapsed,
            block_reads_elapsed,
            individual_reads_elapsed,
            close_elapsed,
            snmp_metadata_elapsed,
            snmp_external_elapsed,
            self._reconnect_count - reconnects_at_start,
            self._recreate_count - recreates_at_start,
        )

        return data

    def _record_modbus_failure(self, reason: str) -> None:
        """Emit one actionable warning for a bounded communication episode."""
        if self._modbus_failure_started is None:
            self._modbus_failure_started = time.monotonic()
        if self._modbus_failure_warning_emitted:
            return
        self._modbus_failure_warning_emitted = True
        _LOGGER.warning(
            "[%s] Modbus communication is unavailable; affected entities may be unavailable. "
            "Home Assistant will retry automatically (%s).",
            self._log_ctx,
            reason,
        )

    def _record_modbus_recovery(self) -> None:
        """Report the first usable poll after a communication episode."""
        if self._modbus_failure_started is None:
            return
        duration = time.monotonic() - self._modbus_failure_started
        _LOGGER.info(
            "[%s] Modbus communication recovered after %.1fs.", self._log_ctx, duration
        )
        self._modbus_failure_started = None
        self._modbus_failure_warning_emitted = False

    def _apply_device_compat_aliases(self, data: dict[str, Any]) -> None:
        """Populate compatibility aliases for device families with sparse maps."""
        if self.device_type in (
            APCDeviceType.SMT_UPS,
            APCDeviceType.SMARTCONNECT_UPS,
        ):
            # APC 990-9840B SMT/SMX/SRT map exposes a measured output frequency
            # register but no dedicated numeric input-frequency register.
            # Keep this as a last-resort fallback after SNMP merge.
            if (
                self.device_type == APCDeviceType.SMT_UPS
                and data.get("input_frequency") is None
                and data.get("output_frequency") is not None
            ):
                data["input_frequency"] = data["output_frequency"]
                _LOGGER.debug(
                    "[%s] input_frequency sourced from output_frequency fallback",
                    self._log_ctx,
                )

    async def _maybe_refresh_snmp_metadata(self) -> None:
        """Refresh device metadata and detect external probes via SNMP.

        Runs at most once per hour (plus first run). External probe availability
        and OID variants are detected during this refresh and cached for normal
        per-cycle polling.
        """
        if self.snmp_availability == "unavailable":
            return
        now = time.monotonic()
        if (
            not self._metadata_needs_refresh
            and (now - self._metadata_last_refresh_monotonic)
            < METADATA_REFRESH_INTERVAL_SECONDS
        ):
            return

        try:
            metadata = await self.hass.async_add_executor_job(
                get_device_metadata_sync,
                self.host,
                self.snmp_community,
                self.device_type,
                self.snmp_port,
            )
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            _LOGGER.debug("[%s] Metadata SNMP query failed: %s", self._log_ctx, err)
            self.set_snmp_availability(False, type(err).__name__)
            return

        if not has_usable_metadata(metadata):
            self.set_snmp_availability(False, "no_metadata")
            return

        self.set_snmp_availability(True)

        self.set_device_metadata(
            hw_model=metadata.get("model"),
            serial_number=metadata.get("serial_number"),
            fw_version=metadata.get("firmware_version") or metadata.get("firmware"),
            fw_date=metadata.get("firmware_date") or metadata.get("hw_version"),
        )

        # Detect which external probes (temp/humidity) are available, and pick the
        # best input-frequency OID. This runs only during the hourly metadata poll.
        try:
            detection = await self.hass.async_add_executor_job(
                detect_external_probe_oids_sync,
                self.host,
                self.snmp_community,
                self.snmp_port,
            )
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            _LOGGER.debug(
                "[%s] External probe detection SNMP query failed: %s",
                self._log_ctx,
                err,
            )
            return

        if isinstance(detection, dict):
            new_detection = {
                str(k): (v if isinstance(v, str) or v is None else str(v))
                for k, v in detection.items()
            }
            old_features = self._snmp_features(self._snmp_probe_detection)
            new_features = self._snmp_features(new_detection)
            self._snmp_probe_detection = new_detection
            added = sorted(new_features - old_features)
            removed = sorted(old_features - new_features)
            if added or removed:
                changes = [
                    *(f"{feature} detected" for feature in added),
                    *(f"{feature} no longer detected" for feature in removed),
                ]
                _LOGGER.info(
                    "[%s] SNMP capabilities changed: %s.",
                    self._log_ctx,
                    "; ".join(changes),
                )
            else:
                _LOGGER.debug("[%s] SNMP capabilities unchanged.", self._log_ctx)

    @staticmethod
    def _snmp_features(detection: dict[str, str | None]) -> set[str]:
        """Map cached OID availability to user-facing capability labels."""
        labels = {
            "temp_1_oid": "External temperature probe 1",
            "humidity_1_oid": "External humidity probe 1",
            "temp_2_oid": "External temperature probe 2",
            "humidity_2_oid": "External humidity probe 2",
            "frequency_oid": "SNMP input-frequency fallback",
        }
        return {label for key, label in labels.items() if detection.get(key)}

    def _merge_device_metadata(self, data: dict[str, Any]) -> None:
        """Inject canonical metadata keys into coordinator data for bridge consumers."""
        data.setdefault("manufacturer", "APC")
        data.setdefault("host", self.host)

        if self.hw_model:
            data["model"] = self.hw_model
        if self.serial_number:
            data["serial_number"] = self.serial_number
        if self.fw_version:
            data["firmware_version"] = self.fw_version
            data.setdefault("firmware", self.fw_version)
        if self.fw_date:
            data["firmware_date"] = self.fw_date
            data.setdefault("hw_version", self.fw_date)

    async def _merge_snmp_external_probe_data(self, data: dict[str, Any]) -> None:
        """Fetch and merge external probe values from SNMP.

        Temp/humidity probes are only polled if they were detected during the
        hourly SNMP metadata refresh. Input frequency is also sourced from SNMP
        (when available) in the same update cycle as Modbus.
        """
        if self.snmp_availability != "available":
            return
        detection = self._snmp_probe_detection
        if not isinstance(detection, dict) or not detection:
            return

        # Only poll SNMP line frequency when Modbus didn't provide it. This is
        # especially important for SMT devices where Modbus may lack input freq.
        effective_detection = dict(detection)
        if data.get("input_frequency") is not None:
            effective_detection["frequency_oid"] = None

        if not any(v for v in effective_detection.values() if v):
            return
        try:
            snmp_values = await self.hass.async_add_executor_job(
                get_external_probe_data_detected_sync,
                self.host,
                self.snmp_community,
                effective_detection,
                self.snmp_port,
            )
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            _LOGGER.debug(
                "[%s] External probe SNMP query failed: %s", self._log_ctx, err
            )
            return

        for key, value in snmp_values.items():
            if value is None:
                continue
            if key == "snmp_input_frequency":
                # Prefer true line frequency from SNMP when Modbus lacks it.
                if data.get("input_frequency") is None:
                    data["input_frequency"] = value
                    _LOGGER.debug(
                        "[%s] input_frequency sourced from SNMP fallback",
                        self._log_ctx,
                    )
                else:
                    _LOGGER.debug(
                        "[%s] SNMP input_frequency available but Modbus value retained",
                        self._log_ctx,
                    )
                continue
            data[key] = value

    async def _merge_snmp_self_test_data(self, data: dict[str, Any]) -> None:
        """Refresh and merge Smart-UPS self-test telemetry once per minute."""
        if self.snmp_availability != "available" or self.device_type not in (
            APCDeviceType.SMART_UPS,
            APCDeviceType.SMT_UPS,
        ):
            return
        now = time.monotonic()
        if (
            now - self._self_test_last_refresh_monotonic
            < SELF_TEST_REFRESH_INTERVAL_SECONDS
        ):
            data.update(self._snmp_self_test_data)
            return
        try:
            values = await self.hass.async_add_executor_job(
                get_self_test_data_sync,
                self.host,
                self.snmp_community,
                self.snmp_port,
            )
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            _LOGGER.debug("[%s] Self-test SNMP query failed: %s", self._log_ctx, err)
            data.update(self._snmp_self_test_data)
            return
        if isinstance(values, dict):
            self._snmp_self_test_data = values
            self._self_test_last_refresh_monotonic = now
            data.update(values)

    @property
    def keep_connection_open_enabled(self) -> bool:
        """Return whether open-session mode is enabled."""
        return self._keep_connection_open

    async def async_set_keep_connection_open(self, enabled: bool) -> None:
        """Update open-session mode at runtime."""
        enabled = bool(enabled)
        async with self._io_lock:
            if self._keep_connection_open == enabled:
                return

            self._keep_connection_open = enabled
            if not enabled:
                # Returning to legacy per-cycle close mode: drop any existing long-lived socket.
                await self._transport.close()
                self._last_io_monotonic = 0.0

        _LOGGER.info(
            "[%s] Persistent Modbus connection %s.",
            self._log_ctx,
            "enabled" if self._keep_connection_open else "disabled",
        )

    def mark_snmp_metadata_refresh_needed(self) -> None:
        """Force SNMP metadata/probe detection refresh on next poll cycle."""
        if self.snmp_availability == "unavailable":
            return
        self._metadata_needs_refresh = True

    async def async_retry_snmp_metadata(self) -> bool:
        """Perform the user-requested SNMP retry, including unavailable entries."""
        try:
            metadata = await self.hass.async_add_executor_job(
                get_device_metadata_sync,
                self.host,
                self.snmp_community,
                self.device_type,
                self.snmp_port,
            )
        except (OSError, TimeoutError, RuntimeError, ValueError) as err:
            self.set_snmp_availability(False, type(err).__name__)
            return False
        if not has_usable_metadata(metadata):
            self.set_snmp_availability(False, "no_metadata")
            return False
        self.set_device_metadata(
            hw_model=metadata.get("model"),
            serial_number=metadata.get("serial_number"),
            fw_version=metadata.get("firmware_version") or metadata.get("firmware"),
            fw_date=metadata.get("firmware_date") or metadata.get("hw_version"),
        )
        self.set_snmp_availability(True)
        self._metadata_needs_refresh = True
        return True

    def _reconnect_pacing_remaining(self) -> float:
        """Seconds still required before the next TCP connect, if any."""
        return self._transport.reconnect_pacing_remaining()

    async def _await_reconnect_pacing(self) -> None:
        """Wait out the minimum gap some devices need after closing a connection."""
        await self._transport._await_reconnect_pacing()

    def _mark_closed(self) -> None:
        """Record when the TCP connection was closed, for reconnect pacing."""
        self._transport._mark_closed()

    async def _ensure_connection(self) -> bool:
        """Ensure Modbus client is connected before starting reads."""
        return await self._transport.ensure_connection()

    def _mark_io_activity(self) -> None:
        """Record the latest successful Modbus socket activity time."""
        self._transport.mark_io_activity()

    def _record_transport_failure(self, err: Exception) -> None:
        """Promote only for socket-style failures, never Modbus exceptions."""
        self._transport.record_failure(err)

    async def _async_reconnect(self, *, reason: str, recreate_client: bool) -> bool:
        """Reconnect the Modbus socket, optionally recreating the client object."""
        return await self._transport.reconnect(
            reason=reason, recreate_client=recreate_client
        )

    async def _recreate_client(self) -> None:
        """Close and recreate the Modbus client to clear dead sockets."""
        await self._transport._recreate_client()

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
                    _LOGGER.debug(
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
                self._mark_io_activity()
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

            except (
                ConnectionException,
                ModbusException,
                OSError,
                TimeoutError,
                TypeError,
            ) as err:
                self._record_transport_failure(err)
                _LOGGER.debug(
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
                        recreate_for_socket_error = (
                            "broken pipe" in err_str or "reset" in err_str
                        )
                        reconnected = await self._async_reconnect(
                            reason=f"block:{block['name']}:{type(err).__name__}",
                            recreate_client=recreate_for_socket_error,
                        )
                        if not reconnected and not recreate_for_socket_error:
                            reconnected = await self._async_reconnect(
                                reason=f"block:{block['name']}:retry_recreate",
                                recreate_client=True,
                            )
                        if not reconnected:
                            raise ConnectionException("Reconnect failed")

                        # Retry the block read
                        read_request = self._build_read_request(
                            block["start_address"], block["count"]
                        )
                        result = await self.hass.async_add_executor_job(read_request)

                        if not self._is_error_response(result):
                            self._mark_io_activity()
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
                        TypeError,
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

        # Fall back when any block or decode failed; partial data is not a complete poll.
        return block_success_count == len(self.register_blocks) and not errors

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
                        _LOGGER.debug(
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
                    _LOGGER.debug(
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
            self._mark_io_activity()
            return result
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            self._record_transport_failure(err)
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
                    recreate_for_socket_error = (
                        "broken pipe" in err_str or "reset" in err_str
                    )
                    reconnected = await self._async_reconnect(
                        reason=f"register:{descriptor['key']}:{type(err).__name__}",
                        recreate_client=recreate_for_socket_error,
                    )
                    if not reconnected and not recreate_for_socket_error:
                        reconnected = await self._async_reconnect(
                            reason=f"register:{descriptor['key']}:retry_recreate",
                            recreate_client=True,
                        )
                    if not reconnected:
                        return None

                    # Retry the read
                    read_request = self._build_read_request(
                        descriptor["address"], descriptor["count"]
                    )
                    result = await self.hass.async_add_executor_job(read_request)
                    self._mark_io_activity()
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
                    # One char per register (legacy Smart-UPS UPS ID chars).
                    # Some firmware stores the character in LSB, others in MSB.
                    # Prefer a printable byte and ignore 0x00 padding.
                    hi = (reg >> 8) & 0xFF
                    lo = reg & 0xFF
                    hi_printable = 0x20 <= hi <= 0x7E
                    lo_printable = 0x20 <= lo <= 0x7E

                    if hi_printable and not lo_printable:
                        chars.append(chr(hi))
                    elif lo_printable and not hi_printable:
                        chars.append(chr(lo))
                    elif hi_printable and lo_printable:
                        # Keep existing behavior deterministic for rare dual-printable case.
                        chars.append(chr(lo))
                    else:
                        chars.append("\x00")
                else:
                    # Two chars per register: MSB first (big-endian)
                    chars.append(chr((reg >> 8) & 0xFF))
                    chars.append(chr(reg & 0xFF))
            # Normalize common device padding so empty/unset strings decode cleanly.
            return "".join(chars).replace("\x00", "").strip()
        else:
            return None

        energy_wh_multiplier = descriptor.get("energy_wh_multiplier")
        if energy_wh_multiplier is not None:
            return raw * energy_wh_multiplier
        if scale and scale != 1:
            return raw / scale

        return raw
