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


def create_modbus_client(host: str, port: int, timeout: int) -> ModbusTcpClient:
    """Create a client with automatic request retries disabled."""
    return ModbusTcpClient(host=host, port=port, timeout=timeout, retries=0)


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
        # Minimum gap between closing a TCP connection and opening the next one.
        # Some devices (SmartConnect UPS) briefly refuse new connections right
        # after a previous one closes, in both persistent-session reconnects
        # and one-request-per-connection polling. 0 = no extra gap enforced.
        # SmartConnect overrides this in set_device_type().
        self._min_reconnect_delay = 0.0
        self._last_close_monotonic = 0.0
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
        self.write_capabilities: set[str] = set()
        self.write_capability_outcomes: dict[str, ProbeOutcome] = {}
        self.write_capability_unresolved: set[str] = set()
        from .write_support import RELEASE_SUPPORTED_SKUS

        self.write_supported_skus = RELEASE_SUPPORTED_SKUS
        self.raw_modbus_model: str | None = None
        self.raw_modbus_sku: str | None = None
        self.raw_modbus_firmware: str | None = None
        self.modbus_map_id: str | None = None
        self._write_pending: set[str] = set()
        self._write_outcomes_unknown: dict[str, tuple[str, str | None, int | None]] = {}
        self._write_reconcile_attempts = 3
        self._write_reconcile_delay = 0.5
        # Registers and blocks (loaded from factory based on device type)
        self.registers: list[dict[str, Any]] = registers_smart_ups.REGISTERS
        self.register_blocks: list[dict[str, Any]] = registers_smart_ups.REGISTER_BLOCKS
        self.register_map: dict[int, dict[str, Any]] = registers_smart_ups.REGISTER_MAP
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._unit_param_candidates: list[str] = [
            name for name in ("device_id", "slave", "unit") if name in read_params
        ]
        self._resolved_unit_param: str | None = None
        self._resolved_write_call: dict[str, tuple[str, str | None]] = {}
        self._output_energy_completed_rollovers = output_energy_completed_rollovers
        self._output_energy_tracker = OutputEnergyTracker.from_storage(
            None, self._output_energy_completed_rollovers
        )
        self._output_energy_store = Store[dict[str, Any]](
            hass, 1, f"{DOMAIN}.{entry_id}_output_energy"
        )
        self._output_energy_tracker_restored = False

    async def async_restore_output_energy_tracker(self) -> None:
        """Restore the SMT output-energy tracker before its first update."""
        state = await self._output_energy_store.async_load()
        self._output_energy_tracker = OutputEnergyTracker.from_storage(
            state, self._output_energy_completed_rollovers
        )
        self._output_energy_tracker_restored = True

    async def _async_track_output_energy(self, data: dict[str, Any]) -> None:
        """Keep the SMT-compatible output-energy counter in canonical Wh."""
        raw_wh = data.get("output_energy")
        if self.device_type not in (
            APCDeviceType.SMT_UPS,
            APCDeviceType.SMARTCONNECT_UPS,
        ) or not isinstance(raw_wh, int):
            return
        if self.device_type == APCDeviceType.SMARTCONNECT_UPS and raw_wh == 2**32 - 1:
            data.pop("output_energy", None)
            data.pop("output_energy_rollover", None)
            return
        if not self._output_energy_tracker_restored:
            await self.async_restore_output_energy_tracker()
        total_wh, reason = self._output_energy_tracker.update(
            raw_wh, self.serial_number
        )
        if reason == "pending_reset":
            _LOGGER.warning(
                "[%s] Rejected Output Energy counter decrease to %d Wh; "
                "awaiting reset confirmation",
                self._log_ctx,
                raw_wh,
            )
        elif reason == "reset":
            _LOGGER.warning(
                "[%s] Confirmed Output Energy meter reset at %d Wh; preserving continuity",
                self._log_ctx,
                raw_wh,
            )
        data["output_energy"] = total_wh
        data["output_energy_rollover"] = self._output_energy_tracker.rollover_count
        if reason != "pending_reset":
            self._output_energy_store.async_delay_save(
                self._output_energy_tracker.as_dict,
                OUTPUT_ENERGY_STORE_SAVE_DELAY_SECONDS,
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

    @property
    def modbus_write_capable(self) -> bool:
        """Return whether any independently discovered write feature is usable."""
        return bool(self.write_capabilities)

    async def _probe_write_evidence(
        self, address: int, count: int, name: str
    ) -> ProbeOutcome:
        """Read capability evidence once, retrying only a transport failure."""
        outcome = await self._probe_outcome(address, count, name)
        if outcome.kind == ProbeKind.TRANSPORT_FAILURE:
            if not await self._ensure_connection():
                return outcome
            outcome = await self._probe_outcome(address, count, name)
        return outcome

    async def _close_write_discovery_connection(self) -> None:
        """Apply the normal close policy after the one-time discovery pass."""
        if self.transport_mode != "session" or self.effective_keep_connection_open:
            return
        try:
            await self.hass.async_add_executor_job(self.client.close)
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.debug("[%s] Write discovery close failed: %s", self._log_ctx, err)
        finally:
            self._last_io_monotonic = 0.0
            self._mark_closed()

    async def async_discover_write_capabilities(self) -> set[str]:
        """Discover exact write features using read-only companion evidence."""
        from .write_support import (
            OUTLET_CAPABILITIES,
            OUTLET_STATUS_ADDRESSES,
            PROTOCOL_TESTS,
            WriteCapability,
            decode_alarm_status,
            decode_battery_test_status,
            decode_outlet_status,
            decode_runtime_calibration_status,
            parse_firmware,
            protocol_constants_valid,
            release_sku_supported,
        )

        self.write_capabilities.clear()
        self.write_capability_outcomes.clear()
        self.write_capability_unresolved.clear()
        self.modbus_map_id = None
        all_capabilities = {capability.value for capability in WriteCapability}
        if self.device_type not in (
            APCDeviceType.SMT_UPS,
            APCDeviceType.SMARTCONNECT_UPS,
        ):
            return set()
        if getattr(self.client, "retries", None) != 0:
            return set()
        if not self.raw_modbus_sku or parse_firmware(self.raw_modbus_firmware) is None:
            self.write_capability_unresolved.update(all_capabilities)
            return set()
        if not release_sku_supported(
            self.raw_modbus_sku,
            self.raw_modbus_firmware,
            self.write_supported_skus,
        ):
            return set()

        async with self._io_lock:
            if not await self._ensure_connection():
                self.write_capability_unresolved.update(all_capabilities)
                return set()
            map_outcome = await self._probe_write_evidence(0x0800, 2, "modbus_map_id")
            if map_outcome.kind == ProbeKind.RESPONSE:
                self.modbus_map_id = self._decode_register(
                    list(map_outcome.registers), {"type": "ascii"}
                )
            protocol_outcomes = {
                address: await self._probe_write_evidence(
                    address, len(expected), f"write_protocol_{address:04x}"
                )
                for address, expected in PROTOCOL_TESTS.items()
            }
            protocol_values = {
                address: outcome.registers
                for address, outcome in protocol_outcomes.items()
                if outcome.kind == ProbeKind.RESPONSE
            }
            identity_outcomes = [map_outcome, *protocol_outcomes.values()]
            if any(
                outcome.kind not in (ProbeKind.RESPONSE, ProbeKind.MODBUS_EXCEPTION)
                or (
                    outcome.kind == ProbeKind.MODBUS_EXCEPTION
                    and not outcome.unsupported
                )
                for outcome in identity_outcomes
            ):
                self.write_capability_unresolved.update(all_capabilities)
                await self._close_write_discovery_connection()
                return set()
            if not self.modbus_map_id:
                self.write_capability_unresolved.update(all_capabilities)
                await self._close_write_discovery_connection()
                return set()
            if not protocol_constants_valid(protocol_values):
                await self._close_write_discovery_connection()
                return set()

            presence = await self._probe_write_evidence(
                0x024E, 1, "write_outlet_presence"
            )
            presence_word = (
                presence.registers[0]
                if presence.kind == ProbeKind.RESPONSE and presence.registers
                else None
            )
            presence_valid = presence_word is not None and not (presence_word & 0xFFE0)
            presence_unresolved = presence.kind not in (
                ProbeKind.RESPONSE,
                ProbeKind.MODBUS_EXCEPTION,
            ) or (
                presence.kind == ProbeKind.MODBUS_EXCEPTION and not presence.unsupported
            )
            if presence.kind == ProbeKind.RESPONSE and not presence_valid:
                presence_unresolved = True

            for target, capability in OUTLET_CAPABILITIES.items():
                outcome = await self._probe_write_evidence(
                    OUTLET_STATUS_ADDRESSES[target],
                    2,
                    f"write_{capability.value}",
                )
                self.write_capability_outcomes[capability.value] = outcome
                decoded_outlet = (
                    decode_outlet_status(
                        (outcome.registers[0] << 16) | outcome.registers[1]
                    )
                    if outcome.kind == ProbeKind.RESPONSE
                    else None
                )
                if presence_unresolved or (
                    outcome.kind not in (ProbeKind.RESPONSE, ProbeKind.MODBUS_EXCEPTION)
                    or (
                        outcome.kind == ProbeKind.MODBUS_EXCEPTION
                        and not outcome.unsupported
                    )
                    or (decoded_outlet is not None and not decoded_outlet.valid)
                ):
                    self.write_capability_unresolved.add(capability.value)
                target_bit = list(OUTLET_CAPABILITIES).index(target)
                if (
                    presence_valid
                    and presence_word & (1 << target_bit)
                    and decoded_outlet is not None
                    and decoded_outlet.valid
                ):
                    self.write_capabilities.add(capability.value)

            for capability, address, decoder in (
                (WriteCapability.BATTERY_TEST, 0x0017, decode_battery_test_status),
                (
                    WriteCapability.RUNTIME_CALIBRATION,
                    0x0018,
                    decode_runtime_calibration_status,
                ),
                (WriteCapability.AUDIBLE_ALARM, 0x001A, decode_alarm_status),
            ):
                outcome = await self._probe_write_evidence(
                    address, 1, f"write_{capability.value}"
                )
                self.write_capability_outcomes[capability.value] = outcome
                decoded_status = (
                    decoder(outcome.registers[0])
                    if outcome.kind == ProbeKind.RESPONSE
                    else None
                )
                if (
                    outcome.kind
                    not in (
                        ProbeKind.RESPONSE,
                        ProbeKind.MODBUS_EXCEPTION,
                    )
                    or (
                        outcome.kind == ProbeKind.MODBUS_EXCEPTION
                        and not outcome.unsupported
                    )
                    or (decoded_status is not None and not decoded_status.valid)
                ):
                    self.write_capability_unresolved.add(capability.value)
                if (
                    decoded_status is not None
                    and outcome.registers[0] != 0xFFFF
                    and decoded_status.valid
                ):
                    self.write_capabilities.add(capability.value)

            setting_capabilities = (
                WriteCapability.OUTLET_SETTINGS_MOG,
                WriteCapability.OUTLET_SETTINGS_SOG_0,
                WriteCapability.OUTLET_SETTINGS_SOG_1,
                WriteCapability.OUTLET_SETTINGS_SOG_2,
            )
            for index, capability in enumerate(setting_capabilities):
                outcome = await self._probe_write_evidence(
                    0x0405 + index * 5, 5, f"write_{capability.value}"
                )
                self.write_capability_outcomes[capability.value] = outcome
                invalid_setting_response = outcome.kind == ProbeKind.RESPONSE and any(
                    (
                        outcome.registers[0] == 0xFFFF,
                        outcome.registers[1] == 0xFFFF,
                        outcome.registers[2:4] == (0xFFFF, 0xFFFF),
                        outcome.registers[4] == 0xFFFF,
                    )
                )
                if presence_unresolved or (
                    outcome.kind not in (ProbeKind.RESPONSE, ProbeKind.MODBUS_EXCEPTION)
                    or (
                        outcome.kind == ProbeKind.MODBUS_EXCEPTION
                        and not outcome.unsupported
                    )
                    or invalid_setting_response
                ):
                    self.write_capability_unresolved.add(capability.value)
                if (
                    presence_valid
                    and presence_word & (1 << index)
                    and outcome.kind == ProbeKind.RESPONSE
                    and not invalid_setting_response
                ):
                    self.write_capabilities.add(capability.value)

            await self._close_write_discovery_connection()

        return set(self.write_capabilities)

    def _write_validation_error(self, translation_key: str, **placeholders: str):
        from homeassistant.exceptions import ServiceValidationError

        return ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=translation_key,
            translation_placeholders=placeholders or None,
        )

    def _write_error(self, translation_key: str, **placeholders: str):
        from homeassistant.exceptions import HomeAssistantError

        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=translation_key,
            translation_placeholders=placeholders or None,
        )

    def _write_call_form(self, method_name: str) -> tuple[str, str | None]:
        """Resolve a write unit-ID signature before the no-replay boundary."""
        cached = self._resolved_write_call.get(method_name)
        if cached:
            return cached
        parameters = inspect.signature(getattr(self.client, method_name)).parameters
        for candidate in ("device_id", "slave", "unit"):
            if (
                candidate in parameters
                and parameters[candidate].kind != parameters[candidate].POSITIONAL_ONLY
            ):
                form = ("keyword", candidate)
                break
        else:
            positional = [
                parameter
                for parameter in parameters.values()
                if parameter.kind
                in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_varargs = any(
                parameter.kind == parameter.VAR_POSITIONAL
                for parameter in parameters.values()
            )
            form = (
                ("positional", None)
                if has_varargs or len(positional) >= 3
                else ("none", None)
            )
        self._resolved_write_call[method_name] = form
        return form

    def _write_registers_compat(
        self, address: int, words: tuple[int, ...], invoked: list[bool]
    ):
        """Invoke exactly one compatible pymodbus write call."""
        method_name = "write_register" if len(words) == 1 else "write_registers"
        write_fn = getattr(self.client, method_name)
        form, unit_name = self._write_call_form(method_name)
        parameters = inspect.signature(write_fn).parameters
        response_option = (
            {"no_response_expected": False}
            if "no_response_expected" in parameters
            else {}
        )
        payload: int | list[int] = words[0] if len(words) == 1 else list(words)
        invoked[0] = True
        if form == "keyword":
            return write_fn(
                address,
                payload,
                **{str(unit_name): self.unit},
                **response_option,
            )
        if form == "positional":
            return write_fn(address, payload, self.unit, **response_option)
        return write_fn(address, payload, **response_option)

    def _write_one_request(
        self, address: int, words: tuple[int, ...], invoked: list[bool]
    ):
        """Open, write once, and close for constrained APC TCP servers."""
        remaining = self._reconnect_pacing_remaining()
        if remaining > 0:
            time.sleep(remaining)
        if not self.client.connect():
            raise ConnectionException("Unable to open Modbus connection")
        try:
            return self._write_registers_compat(address, words, invoked)
        finally:
            self.client.close()
            self._mark_closed()

    def _write_precondition(self, operation: str, target: str | None) -> str | None:
        """Recheck capability and current state immediately before a write."""
        from .write_support import (
            OUTLET_CAPABILITIES,
            OUTLET_STATUS_KEYS,
            OutletAction,
            OutletTarget,
            WriteCapability,
            WriteOperation,
            alarm_precondition,
            decode_alarm_status,
            decode_battery_test_status,
            decode_outlet_status,
            decode_runtime_calibration_status,
            operation_precondition,
            outlet_precondition,
        )

        write_operation = WriteOperation(operation)
        if write_operation == WriteOperation.OUTLET:
            if target is None:
                return "invalid_operation"
            target_name, action_name = target.split(":", 1)
            outlet_target = OutletTarget(target_name)
            if OUTLET_CAPABILITIES[outlet_target].value not in self.write_capabilities:
                return "write_not_supported"
            statuses = {
                candidate: decode_outlet_status(raw)
                for candidate, key in OUTLET_STATUS_KEYS.items()
                if OUTLET_CAPABILITIES[candidate].value in self.write_capabilities
                and isinstance((raw := self.data.get(key)), int)
            }
            return outlet_precondition(
                OutletAction(action_name), outlet_target, statuses
            )
        if write_operation in (
            WriteOperation.BATTERY_TEST_START,
            WriteOperation.BATTERY_TEST_ABORT,
        ):
            if WriteCapability.BATTERY_TEST.value not in self.write_capabilities:
                return "write_not_supported"
            raw = self.data.get("battery_test_status")
            if not isinstance(raw, int):
                return "write_state_unavailable"
            return operation_precondition(
                "start"
                if write_operation == WriteOperation.BATTERY_TEST_START
                else "abort",
                decode_battery_test_status(raw),
            )
        if write_operation in (
            WriteOperation.CALIBRATION_START,
            WriteOperation.CALIBRATION_ABORT,
        ):
            if WriteCapability.RUNTIME_CALIBRATION.value not in self.write_capabilities:
                return "write_not_supported"
            raw = self.data.get("runtime_calibration_status")
            if not isinstance(raw, int):
                return "write_state_unavailable"
            return operation_precondition(
                "start"
                if write_operation == WriteOperation.CALIBRATION_START
                else "abort",
                decode_runtime_calibration_status(raw),
            )
        if WriteCapability.AUDIBLE_ALARM.value not in self.write_capabilities:
            return "write_not_supported"
        raw = self.data.get("user_interface_status")
        if not isinstance(raw, int):
            return "write_state_unavailable"
        return alarm_precondition(
            write_operation == WriteOperation.ALARM_MUTE,
            decode_alarm_status(raw),
        )

    @staticmethod
    def _write_pending_key(operation: str, target: str | None) -> str:
        """Return the conflict key shared by execution and entity availability."""
        from .write_support import WriteOperation

        write_operation = WriteOperation(operation)
        if write_operation == WriteOperation.OUTLET:
            if target is None:
                raise ValueError("missing outlet target")
            target_name, _ = target.split(":", 1)
            return f"outlet:{target_name}"
        if write_operation in (
            WriteOperation.ALARM_MUTE,
            WriteOperation.ALARM_CANCEL_MUTE,
        ):
            return "audible_alarm"
        return write_operation.value.split("_start", 1)[0].split("_abort", 1)[0]

    def write_operation_available(
        self, operation: str, target: str | None = None
    ) -> bool:
        """Return whether current state and conflict markers allow an operation."""
        try:
            pending_key = self._write_pending_key(operation, target)
            return bool(
                self._write_precondition(operation, target) is None
                and pending_key not in self._write_pending
                and pending_key not in self._write_outcomes_unknown
            )
        except (KeyError, TypeError, ValueError):
            return False

    @staticmethod
    def _write_initial_status(
        operation: str, target: str | None, data: dict[str, Any]
    ) -> int | None:
        """Capture the companion word used to prove a later state transition."""
        from .write_support import OUTLET_STATUS_KEYS, OutletTarget, WriteOperation

        write_operation = WriteOperation(operation)
        if write_operation == WriteOperation.OUTLET and target:
            target_name, _ = target.split(":", 1)
            value = data.get(OUTLET_STATUS_KEYS[OutletTarget(target_name)])
        elif write_operation in (
            WriteOperation.BATTERY_TEST_START,
            WriteOperation.BATTERY_TEST_ABORT,
        ):
            value = data.get("battery_test_status")
        elif write_operation in (
            WriteOperation.CALIBRATION_START,
            WriteOperation.CALIBRATION_ABORT,
        ):
            value = data.get("runtime_calibration_status")
        else:
            value = data.get("user_interface_status")
        return value if isinstance(value, int) else None

    @staticmethod
    def _write_status_reconciled(
        operation: str,
        target: str | None,
        initial_raw: int | None,
        data: dict[str, Any],
    ) -> bool:
        """Return true only when companion status proves command progress."""
        from .write_support import (
            OUTLET_STATUS_KEYS,
            OutletAction,
            OutletTarget,
            WriteOperation,
            decode_alarm_status,
            decode_battery_test_status,
            decode_outlet_status,
            decode_runtime_calibration_status,
        )

        write_operation = WriteOperation(operation)
        if write_operation == WriteOperation.OUTLET and target:
            target_name, action_name = target.split(":", 1)
            raw = data.get(OUTLET_STATUS_KEYS[OutletTarget(target_name)])
            if not isinstance(raw, int):
                return False
            status = decode_outlet_status(raw)
            if not status.valid:
                return False
            action = OutletAction(action_name)
            if action == OutletAction.ON:
                return status.is_on or status.pending
            if action == OutletAction.OFF:
                return status.is_off or status.pending
            if action == OutletAction.CANCEL:
                return not status.pending
            if action == OutletAction.SHUTDOWN:
                return status.is_off or status.pending
            return status.is_off or status.pending

        if write_operation in (
            WriteOperation.BATTERY_TEST_START,
            WriteOperation.BATTERY_TEST_ABORT,
        ):
            raw = data.get("battery_test_status")
            status = decode_battery_test_status(raw) if isinstance(raw, int) else None
            if not status or not status.valid:
                return False
            if write_operation == WriteOperation.BATTERY_TEST_START:
                return status.active or (
                    raw != initial_raw and status.state != "unknown"
                )
            return status.state == "aborted" or (
                raw != initial_raw
                and status.state not in ("pending", "in_progress", "unknown")
            )

        if write_operation in (
            WriteOperation.CALIBRATION_START,
            WriteOperation.CALIBRATION_ABORT,
        ):
            raw = data.get("runtime_calibration_status")
            status = (
                decode_runtime_calibration_status(raw) if isinstance(raw, int) else None
            )
            if not status or not status.valid:
                return False
            if write_operation == WriteOperation.CALIBRATION_START:
                return status.active or (
                    raw != initial_raw and status.state != "unknown"
                )
            return status.state == "aborted" or (
                raw != initial_raw
                and status.state not in ("pending", "in_progress", "unknown")
            )

        raw = data.get("user_interface_status")
        status = decode_alarm_status(raw) if isinstance(raw, int) else None
        if not status or not status.valid:
            return False
        return (
            status.muted
            if write_operation == WriteOperation.ALARM_MUTE
            else not status.muted and raw != initial_raw
        )

    def _clear_reconciled_unknown_writes(self, data: dict[str, Any]) -> None:
        """Let ordinary polling resolve a bounded unknown write outcome."""
        for key, (operation, target, initial_raw) in list(
            self._write_outcomes_unknown.items()
        ):
            if self._write_status_reconciled(operation, target, initial_raw, data):
                self._write_outcomes_unknown.pop(key, None)

    async def async_execute_write(
        self, operation: str, target: str | None = None
    ) -> None:
        """Execute one allowlisted command with an observable no-replay boundary."""
        from .write_support import (
            COMMANDS,
            OutletAction,
            OutletTarget,
            WriteOperation,
            build_outlet_command,
            validate_write_multiple_response,
            validate_write_single_response,
        )

        try:
            write_operation = WriteOperation(operation)
            if write_operation == WriteOperation.OUTLET:
                if target is None:
                    raise ValueError
                target_name, action_name = target.split(":", 1)
                words = build_outlet_command(
                    OutletAction(action_name), OutletTarget(target_name)
                )
                address = 0x0602
            else:
                address, words = COMMANDS[write_operation]
            pending_key = self._write_pending_key(operation, target)
        except (KeyError, TypeError, ValueError) as err:
            raise self._write_validation_error("invalid_operation") from err

        invoked = [False]
        response = None
        initial_raw: int | None = None
        async with self._io_lock:
            precondition = self._write_precondition(operation, target)
            if precondition:
                raise self._write_validation_error(precondition)
            if pending_key in self._write_pending:
                raise self._write_validation_error("operation_already_active")
            if pending_key in self._write_outcomes_unknown:
                raise self._write_validation_error("write_outcome_unresolved")
            if getattr(self.client, "retries", None) != 0:
                raise self._write_error("write_retry_policy_unverified")
            self._write_pending.add(pending_key)
            initial_raw = self._write_initial_status(operation, target, self.data)
            try:
                try:
                    if self.transport_mode == "one_request_per_connection":
                        request = functools.partial(
                            self._write_one_request, address, words, invoked
                        )
                    else:
                        if not await self._ensure_connection():
                            raise ConnectionException(
                                "Unable to open Modbus connection"
                            )
                        request = functools.partial(
                            self._write_registers_compat, address, words, invoked
                        )
                    response = await self.hass.async_add_executor_job(request)
                    valid = (
                        validate_write_single_response(response, address, words[0])
                        if len(words) == 1
                        else validate_write_multiple_response(
                            response, address, len(words)
                        )
                    )
                    if valid:
                        self._mark_io_activity()
                finally:
                    if (
                        self.transport_mode == "session"
                        and invoked[0]
                        and not self.effective_keep_connection_open
                    ):
                        try:
                            await self.hass.async_add_executor_job(self.client.close)
                        finally:
                            self._mark_closed()
            except Exception as err:
                if not invoked[0]:
                    self._write_pending.discard(pending_key)
                    raise self._write_error("write_not_sent") from err

        if not invoked[0]:
            raise self._write_error("write_not_sent")

        reconciled = False
        for attempt in range(self._write_reconcile_attempts):
            try:
                await self.async_request_refresh()
            except Exception as err:
                _LOGGER.debug(
                    "[%s] Write reconciliation attempt failed: %s", self._log_ctx, err
                )
                if attempt + 1 == self._write_reconcile_attempts:
                    self._write_pending.discard(pending_key)
                    self._write_outcomes_unknown[pending_key] = (
                        operation,
                        target,
                        initial_raw,
                    )
                    raise self._write_error("write_outcome_unknown") from err
            if self._write_status_reconciled(operation, target, initial_raw, self.data):
                reconciled = True
                break
            if attempt + 1 < self._write_reconcile_attempts:
                await asyncio.sleep(self._write_reconcile_delay)
        if reconciled:
            self._write_pending.discard(pending_key)
        else:
            self._write_pending.discard(pending_key)
            self._write_outcomes_unknown[pending_key] = (
                operation,
                target,
                initial_raw,
            )
        if not reconciled:
            raise self._write_error("write_outcome_unknown")

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
        """Read one block on a fresh socket for constrained APC TCP servers.

        Runs in an executor thread, so pacing uses a blocking sleep rather
        than asyncio.sleep.
        """
        remaining = self._reconnect_pacing_remaining()
        if remaining > 0:
            _LOGGER.debug(
                "[%s] Waiting %.3fs before reconnect (min gap %.1fs since last close)",
                self._log_ctx,
                remaining,
                self._min_reconnect_delay,
            )
            time.sleep(remaining)
        if not self.client.connect():
            raise ConnectionException("Unable to open Modbus connection")
        try:
            return self._read_holding_registers_compat(address, count)
        finally:
            self.client.close()
            self._mark_closed()

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
                    finally:
                        self._mark_closed()
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
            from .write_support import (
                OUTLET_STATUS_KEYS,
                decode_battery_test_status,
                decode_outlet_status,
                decode_runtime_calibration_status,
            )

            if isinstance(data.get("battery_test_status"), int):
                data["battery_test_operation_state"] = decode_battery_test_status(
                    data["battery_test_status"]
                ).state
            if isinstance(data.get("runtime_calibration_status"), int):
                data["runtime_calibration_operation_state"] = (
                    decode_runtime_calibration_status(
                        data["runtime_calibration_status"]
                    ).state
                )
            for target, key in OUTLET_STATUS_KEYS.items():
                raw = data.get(key)
                if not isinstance(raw, int):
                    continue
                status = decode_outlet_status(raw)
                state = status.process or ("pending" if status.pending else None)
                data[f"outlet_{target.value}_operation_state"] = state or (
                    "on" if status.is_on else "off" if status.is_off else "unknown"
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
                finally:
                    self._mark_closed()
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

    def _reconnect_pacing_remaining(self) -> float:
        """Seconds still required before the next TCP connect, if any."""
        if self._min_reconnect_delay <= 0 or self._last_close_monotonic <= 0:
            return 0.0
        elapsed = time.monotonic() - self._last_close_monotonic
        return max(0.0, self._min_reconnect_delay - elapsed)

    async def _await_reconnect_pacing(self) -> None:
        """Wait out the minimum gap some devices need after closing a connection."""
        remaining = self._reconnect_pacing_remaining()
        if remaining > 0:
            _LOGGER.debug(
                "[%s] Waiting %.3fs before reconnect (min gap %.1fs since last close)",
                self._log_ctx,
                remaining,
                self._min_reconnect_delay,
            )
            await asyncio.sleep(remaining)

    def _mark_closed(self) -> None:
        """Record when the TCP connection was closed, for reconnect pacing."""
        self._last_close_monotonic = time.monotonic()

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
            await self._await_reconnect_pacing()
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
            finally:
                self._mark_closed()

        await self._await_reconnect_pacing()
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
        finally:
            self._mark_closed()
        self.client = create_modbus_client(self.host, self.port, self.timeout)
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._unit_param_candidates = [
            name for name in ("device_id", "slave", "unit") if name in read_params
        ]
        self._resolved_unit_param = None
        self._resolved_write_call.clear()
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

        energy_wh_multiplier = descriptor.get("energy_wh_multiplier")
        if energy_wh_multiplier is not None:
            return raw * energy_wh_multiplier
        if scale and scale != 1:
            return raw / scale

        return raw
