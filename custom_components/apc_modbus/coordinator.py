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
import inspect
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
from homeassistant.helpers.storage import Store

from .const import (
    DEFAULT_IDLE_RECONNECT_SECONDS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .device_types import (
    APCDeviceType,
    classify_device_type,
    ProbeKind,
    ProbeOutcome,
)
from .output_energy_tracker import OutputEnergyTracker
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
        self.client = client
        self.unit = unit
        self.device_name = device_name
        self.host = host
        self.port = port
        self.entry_id = entry_id
        self.timeout = timeout
        self.snmp_community = snmp_community
        self.snmp_port = snmp_port
        self._keep_connection_open = keep_connection_open
        self.transport_mode = (
            "one_request_per_connection"
            if transport_mode == "one_request_per_connection"
            else "session"
        )
        self._transport_mode_persist = transport_mode_persist
        self._session_request_succeeded = False
        self.transport_promotion_reason: str | None = None
        self._idle_reconnect_seconds = DEFAULT_IDLE_RECONNECT_SECONDS
        self._log_ctx = f"{self.device_name} {self.host}:{self.port} (unit {self.unit})"
        # Serialize Modbus client access to avoid concurrent reads on one socket.
        self._io_lock = io_lock
        # Connection/backoff tracking
        self._connect_failures = 0
        self._backoff_until: float | None = None
        self._backoff_base = 2.0
        self._backoff_max = 60.0
        self._last_io_monotonic = 0.0
        self._reconnect_count = 0
        self._recreate_count = 0
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
        # Registers and blocks (loaded from factory based on device type)
        self.registers: list[dict[str, Any]] = registers_smart_ups.REGISTERS
        self.register_blocks: list[dict[str, Any]] = registers_smart_ups.REGISTER_BLOCKS
        self.register_map: dict[int, dict[str, Any]] = registers_smart_ups.REGISTER_MAP
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._unit_param_candidates: list[str] = [
            name for name in ("device_id", "slave", "unit") if name in read_params
        ]
        self._resolved_unit_param: str | None = None
        self._output_energy_tracker = OutputEnergyTracker.from_storage(
            None, output_energy_completed_rollovers
        )
        self._output_energy_store = Store[dict[str, Any]](
            hass, 1, f"{DOMAIN}.{entry_id}_output_energy"
        )
        self._output_energy_tracker_restored = False
        self._output_energy_reset_logged = False

    async def async_restore_output_energy_tracker(self) -> None:
        """Restore the SMT output-energy tracker before its first update."""
        state = await self._output_energy_store.async_load()
        self._output_energy_tracker = OutputEnergyTracker.from_storage(
            state, self._output_energy_tracker.offset_wh // (2**32)
        )
        self._output_energy_tracker_restored = True

    async def _async_track_output_energy(self, data: dict[str, Any]) -> None:
        """Publish and persist the compensated SMT output-energy counter."""
        raw_wh = data.get("output_energy")
        if self.device_type != APCDeviceType.SMT_UPS or not isinstance(raw_wh, int):
            return
        if not self._output_energy_tracker_restored:
            await self.async_restore_output_energy_tracker()
        total_wh, reason = self._output_energy_tracker.update(
            raw_wh, self.serial_number
        )
        if reason == "reset" and not self._output_energy_reset_logged:
            _LOGGER.warning(
                "[%s] Output Energy counter decreased; preserving continuity as a meter reset",
                self._log_ctx,
            )
            self._output_energy_reset_logged = True
        data["output_energy_kwh"] = total_wh / 1000
        self._output_energy_store.async_delay_save(
            self._output_energy_tracker.as_dict, OUTPUT_ENERGY_STORE_SAVE_DELAY_SECONDS
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
        self.device_type = device_type
        _LOGGER.info("Device type set to: %s", device_type.value)
        # Rack PDU is typically slower to respond, so use longer delays.
        if self.device_type == APCDeviceType.RACK_PDU:
            self._post_connect_delay = 0.10
            self._inter_block_delay = 0.10

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

            probes: dict[str, ProbeOutcome] = {}
            for name, address, count in (
                ("rack_pdu_capabilities", 0x009E, 5),
                ("rack_pdu_measurements", 0x00CF, 6),
                ("legacy_ups_id", 0x0021, 1),
                ("smt_status", 0x0000, 23),
                ("smt_measurements", 0x0080, 26),
            ):
                probes[name] = await self._probe_outcome(address, count, name)
                if self.transport_mode == "one_request_per_connection":
                    for retry_name, retry_address, retry_count in (
                        ("rack_pdu_capabilities", 0x009E, 5),
                        ("rack_pdu_measurements", 0x00CF, 6),
                        ("legacy_ups_id", 0x0021, 1),
                        ("smt_status", 0x0000, 23),
                        ("smt_measurements", 0x0080, 26),
                    ):
                        if (
                            probes.get(
                                retry_name, ProbeOutcome(ProbeKind.RESPONSE)
                            ).kind
                            == ProbeKind.TRANSPORT_FAILURE
                        ):
                            probes[retry_name] = await self._probe_outcome(
                                retry_address, retry_count, retry_name
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
        if self.transport_mode != "session" or not self._session_request_succeeded:
            return
        self.transport_mode = "one_request_per_connection"
        self.transport_promotion_reason = reason
        if self._transport_mode_persist:
            self._transport_mode_persist(self.transport_mode)
        _LOGGER.warning(
            "[%s] Promoted Modbus transport mode: %s", self._log_ctx, reason
        )

    def _build_read_request(self, address: int, count: int):
        """Build a compatible read request for old and new pymodbus APIs."""
        if self.transport_mode == "one_request_per_connection":
            return functools.partial(self._read_one_request, address, count)
        return functools.partial(self._read_holding_registers_compat, address, count)

    def _read_one_request(self, address: int, count: int):
        """Read one block on a fresh socket for constrained APC TCP servers."""
        if not self.client.connect():
            raise ConnectionException("Unable to open Modbus connection")
        try:
            return self._read_holding_registers_compat(address, count)
        finally:
            self.client.close()

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
        read_fn = self.client.read_holding_registers

        attempts: list[tuple[str, object]] = []
        if self._resolved_unit_param:
            attempts.append(("kw", self._resolved_unit_param))
        for candidate in self._unit_param_candidates:
            if candidate != self._resolved_unit_param:
                attempts.append(("kw", candidate))
        attempts.extend(
            [
                ("positional", self.unit),
                ("none", None),
            ]
        )

        last_type_error: TypeError | None = None
        for kind, value in attempts:
            try:
                if kind == "kw":
                    result = read_fn(address, count=count, **{str(value): self.unit})
                    self._resolved_unit_param = str(value)
                    return result
                if kind == "positional":
                    return read_fn(address, count, int(value))
                return read_fn(address, count=count)
            except TypeError as err:
                last_type_error = err
                continue

        if last_type_error is not None:
            raise last_type_error
        raise TypeError("No compatible pymodbus read_holding_registers signature found")

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
                        TypeError,
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

        except (
            ConnectionException,
            ModbusException,
            OSError,
            TimeoutError,
            TypeError,
        ) as err:
            _LOGGER.error("Error discovering capabilities: %s", err)

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
                    raise UpdateFailed("Backoff active; skipping update cycle")
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
                    _LOGGER.info(
                        "[%s] Retrying update with fresh connections after transport promotion",
                        self._log_ctx,
                    )
                    data.clear()
                    errors.clear()
                    block_read_ok = await self._try_block_reads(data, errors)

                # If block reads failed, fall back to individual reads with reconnection.
                if not block_read_ok:
                    _LOGGER.info(
                        "[%s] Block reads failed or incomplete, falling back to individual register reads",
                        self._log_ctx,
                    )
                    individual_reads_start = time.monotonic()
                    mode_before_individual_reads = self.transport_mode
                    errors.clear()
                    await self._try_individual_reads(data, errors)
                    individual_reads_elapsed = time.monotonic() - individual_reads_start
                    if self.transport_mode != mode_before_individual_reads:
                        _LOGGER.info(
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
                raise
            except Exception as err:
                self._register_failure(str(err))
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
                    try:
                        close_request = functools.partial(self.client.close)
                        await self.hass.async_add_executor_job(close_request)
                        close_elapsed = time.monotonic() - close_start
                        self._last_io_monotonic = 0.0
                        _LOGGER.debug(
                            "[%s] Closed Modbus client after update (%.3fs)",
                            self._log_ctx,
                            close_elapsed,
                        )
                    except (
                        ConnectionException,
                        ModbusException,
                        OSError,
                        TimeoutError,
                    ) as close_err:
                        _LOGGER.debug(
                            "[%s] Error closing Modbus client: %s",
                            self._log_ctx,
                            close_err,
                        )
                modbus_cycle_elapsed = time.monotonic() - cycle_start

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
            modbus_cycle_elapsed,
        )
        self._reset_backoff()

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

    def _apply_device_compat_aliases(self, data: dict[str, Any]) -> None:
        """Populate compatibility aliases for device families with sparse maps."""
        if self.device_type == APCDeviceType.SMT_UPS:
            # APC 990-9840B SMT/SMX/SRT map exposes a measured output frequency
            # register but no dedicated numeric input-frequency register.
            # Keep this as a last-resort fallback after SNMP merge.
            if (
                data.get("input_frequency") is None
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
            self._snmp_probe_detection = {
                str(k): (v if isinstance(v, str) or v is None else str(v))
                for k, v in detection.items()
            }
            _LOGGER.info(
                "[%s] SNMP probe detection (hourly): temp1=%s hum1=%s temp2=%s hum2=%s freq=%s",
                self._log_ctx,
                bool(self._snmp_probe_detection.get("temp_1_oid")),
                bool(self._snmp_probe_detection.get("humidity_1_oid")),
                bool(self._snmp_probe_detection.get("temp_2_oid")),
                bool(self._snmp_probe_detection.get("humidity_2_oid")),
                bool(self._snmp_probe_detection.get("frequency_oid")),
            )

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
            APCDeviceType.SMARTCONNECT_UPS,
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
                try:
                    close_request = functools.partial(self.client.close)
                    await self.hass.async_add_executor_job(close_request)
                except (ConnectionException, ModbusException, OSError, TimeoutError):
                    pass
                self._last_io_monotonic = 0.0

        _LOGGER.info(
            "[%s] keep_connection_open set to %s",
            self._log_ctx,
            self._keep_connection_open,
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

    async def _ensure_connection(self) -> bool:
        """Ensure Modbus client is connected before starting reads."""
        if self.transport_mode == "one_request_per_connection":
            return True
        if self.effective_keep_connection_open and self._last_io_monotonic > 0:
            idle_for = time.monotonic() - self._last_io_monotonic
            if idle_for >= self._idle_reconnect_seconds:
                _LOGGER.info(
                    "[%s] Modbus socket idle for %.1fs; reconnecting before poll",
                    self._log_ctx,
                    idle_for,
                )
                reconnected = await self._async_reconnect(
                    reason=f"idle>{self._idle_reconnect_seconds:.0f}s",
                    recreate_client=False,
                )
                if not reconnected:
                    reconnected = await self._async_reconnect(
                        reason="idle_reconnect_retry",
                        recreate_client=True,
                    )
                return reconnected

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
                self._mark_io_activity()
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
                self._connect_failures = 0
                ok = await self._async_reconnect(
                    reason="connect_failures>=3",
                    recreate_client=True,
                )
                return ok
            return False
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.debug("[%s] Connection attempt failed: %s", self._log_ctx, err)
            return False

    def _mark_io_activity(self) -> None:
        """Record the latest successful Modbus socket activity time."""
        self._last_io_monotonic = time.monotonic()
        if self.transport_mode == "session":
            self._session_request_succeeded = True

    def _record_transport_failure(self, err: Exception) -> None:
        """Promote only for socket-style failures, never Modbus exceptions."""
        if isinstance(err, ModbusException) and not isinstance(
            err, ConnectionException
        ):
            return
        if isinstance(err, (OSError, TimeoutError, ConnectionException)):
            self._promote_transport_mode(type(err).__name__)

    async def _async_reconnect(self, *, reason: str, recreate_client: bool) -> bool:
        """Reconnect the Modbus socket, optionally recreating the client object."""
        self._reconnect_count += 1
        if recreate_client:
            self._recreate_count += 1
            await self._recreate_client()
        else:
            try:
                close_request = functools.partial(self.client.close)
                await self.hass.async_add_executor_job(close_request)
            except (ConnectionException, ModbusException, OSError, TimeoutError):
                pass

        reconnect_start = time.monotonic()
        connect_request = functools.partial(self.client.connect)
        ok = await self.hass.async_add_executor_job(connect_request)
        _LOGGER.debug(
            "[%s] reconnect(reason=%s, recreate=%s) -> %s (%.3fs, total_reconnects=%d, total_recreates=%d)",
            self._log_ctx,
            reason,
            recreate_client,
            ok,
            time.monotonic() - reconnect_start,
            self._reconnect_count,
            self._recreate_count,
        )
        if ok:
            self._connect_failures = 0
            self._mark_io_activity()
            if self._post_connect_delay > 0:
                await asyncio.sleep(self._post_connect_delay)
        return ok

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
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._unit_param_candidates = [
            name for name in ("device_id", "slave", "unit") if name in read_params
        ]
        self._resolved_unit_param = None
        # Keep cached SNMP metadata/probe detection across Modbus client recreation.

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

        if scale and scale != 1:
            return raw / scale

        return raw
