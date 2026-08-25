# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read, decode, and energy continuity for APC Modbus telemetry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from pymodbus.exceptions import ConnectionException, ModbusException
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import DOMAIN
from .device_types import APCDeviceType
from .modbus_transport import ModbusTransport
from .output_energy_tracker import OutputEnergyTracker

_LOGGER = logging.getLogger(__name__)
_OUTPUT_ENERGY_STORE_SAVE_DELAY_SECONDS = 60


@dataclass
class PollResult:
    """The raw Modbus portion of one coordinator update."""

    data: dict[str, Any]
    errors: list[str]
    lock_wait: float
    elapsed: float
    block_reads_elapsed: float
    individual_reads_elapsed: float
    close_elapsed: float


class ModbusPoller:
    """Poll one register map through the shared transport."""

    def __init__(
        self,
        hass,
        transport: ModbusTransport,
        entry_id: str,
        log_ctx: str,
        completed_rollovers: int,
    ) -> None:
        self._transport = transport
        self._log_ctx = log_ctx
        self.registers: list[dict[str, Any]] = []
        self.register_blocks: list[dict[str, Any]] = []
        self.register_map: dict[int, dict[str, Any]] = {}
        self.inter_block_delay = 0.05
        self._energy_tracker = OutputEnergyTracker.from_storage(
            None, completed_rollovers
        )
        self._energy_store = Store[dict[str, Any]](
            hass, 1, f"{DOMAIN}.{entry_id}_output_energy"
        )
        self._energy_restored = False

    def set_registers(
        self,
        registers: list[dict[str, Any]],
        register_blocks: list[dict[str, Any]],
        register_map: dict[int, dict[str, Any]],
    ) -> None:
        self.registers = registers
        self.register_blocks = register_blocks
        self.register_map = register_map

    async def async_restore_output_energy_tracker(
        self, completed_rollovers: int
    ) -> None:
        state = await self._energy_store.async_load()
        self._energy_tracker = OutputEnergyTracker.from_storage(
            state, completed_rollovers
        )
        self._energy_restored = True

    async def async_track_output_energy(
        self,
        data: dict[str, Any],
        device_type: APCDeviceType,
        serial_number: str | None,
        completed_rollovers: int,
    ) -> None:
        raw_wh = data.get("output_energy")
        if device_type not in (
            APCDeviceType.SMT_UPS,
            APCDeviceType.SMARTCONNECT_UPS,
        ) or not isinstance(raw_wh, int):
            return
        if device_type == APCDeviceType.SMARTCONNECT_UPS and raw_wh == 2**32 - 1:
            data.pop("output_energy", None)
            data.pop("output_energy_rollover", None)
            return
        if not self._energy_restored:
            await self.async_restore_output_energy_tracker(completed_rollovers)
        total_wh, reason = self._energy_tracker.update(raw_wh, serial_number)
        if reason == "pending_reset":
            _LOGGER.warning(
                "[%s] Rejected Output Energy counter decrease to %d Wh; awaiting reset confirmation",
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
        data["output_energy_rollover"] = self._energy_tracker.rollover_count
        if reason != "pending_reset":
            self._energy_store.async_delay_save(
                self._energy_tracker.as_dict, _OUTPUT_ENERGY_STORE_SAVE_DELAY_SECONDS
            )

    async def async_poll(self, *, keep_connection_open: bool) -> PollResult:
        """Read all blocks, falling back to individual register reads."""
        data: dict[str, Any] = {}
        errors: list[str] = []
        lock_start = time.monotonic()
        async with self._transport.io_lock:
            lock_wait = time.monotonic() - lock_start
            cycle_start = time.monotonic()
            if not await self._transport.ensure_connection():
                raise UpdateFailed("Unable to connect to APC UPS")
            mode_before_reads = self._transport.mode
            block_start = time.monotonic()
            block_ok = await self._try_block_reads(data, errors)
            block_elapsed = time.monotonic() - block_start
            if self._transport.mode != mode_before_reads:
                data.clear()
                errors.clear()
                block_ok = await self._try_block_reads(data, errors)
            individual_elapsed = 0.0
            if not block_ok:
                errors.clear()
                individual_start = time.monotonic()
                mode_before_individual = self._transport.mode
                await self._try_individual_reads(data, errors)
                individual_elapsed = time.monotonic() - individual_start
                if self._transport.mode != mode_before_individual:
                    data.clear()
                    errors.clear()
                    block_ok = await self._try_block_reads(data, errors)
                    if not block_ok:
                        await self._try_individual_reads(data, errors)
            close_elapsed = 0.0
            if not keep_connection_open:
                close_start = time.monotonic()
                await self._transport.close()
                self._transport.last_io_monotonic = 0.0
                close_elapsed = time.monotonic() - close_start
            elapsed = time.monotonic() - cycle_start
        return PollResult(
            data,
            errors,
            lock_wait,
            elapsed,
            block_elapsed,
            individual_elapsed,
            close_elapsed,
        )

    async def _try_block_reads(self, data: dict[str, Any], errors: list[str]) -> bool:
        success_count = 0
        for block in self.register_blocks:
            if self.inter_block_delay > 0:
                await asyncio.sleep(self.inter_block_delay)
            try:
                result = await self._read_with_reconnect(
                    block["start_address"], block["count"], f"block:{block['name']}"
                )
                if result is None or self._is_error_response(result):
                    self._mark_block_errors(block, errors)
                    continue
                success_count += 1
                self._decode_block(result.registers, block, data, errors)
            except (
                ConnectionException,
                ModbusException,
                OSError,
                TimeoutError,
                TypeError,
            ) as err:
                _LOGGER.debug(
                    "[%s] Exception in block read %s: %s",
                    self._log_ctx,
                    block["name"],
                    err,
                )
                self._mark_block_errors(block, errors)
        return success_count == len(self.register_blocks) and not errors

    def _mark_block_errors(self, block: dict[str, Any], errors: list[str]) -> None:
        errors.extend(
            self.register_map[address]["key"]
            for address in block["registers"]
            if address in self.register_map
        )

    def _decode_block(
        self,
        registers: list[int],
        block: dict[str, Any],
        data: dict[str, Any],
        errors: list[str],
    ) -> None:
        for address in block["registers"]:
            descriptor = self.register_map.get(address)
            if not descriptor:
                continue
            offset = address - block["start_address"]
            values = registers[offset : offset + descriptor["count"]]
            if len(values) < descriptor["count"]:
                errors.append(descriptor["key"])
                continue
            try:
                value = self.decode_register(values, descriptor)
                if value is not None:
                    data[descriptor["key"]] = value
            except (TypeError, ValueError, KeyError, IndexError) as err:
                errors.append(descriptor["key"])
                _LOGGER.debug("Error decoding register %s: %s", descriptor["key"], err)

    async def _try_individual_reads(
        self, data: dict[str, Any], errors: list[str]
    ) -> None:
        failures = 0
        for descriptor in self.registers:
            try:
                result = await self._read_with_reconnect(
                    descriptor["address"],
                    descriptor["count"],
                    f"register:{descriptor['key']}",
                )
                if result is None or self._is_error_response(result):
                    errors.append(descriptor["key"])
                    failures += 1
                else:
                    failures = 0
                    value = self.decode_register(result.registers, descriptor)
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
                failures += 1
                _LOGGER.debug(
                    "[%s] Exception reading register %s: %s",
                    self._log_ctx,
                    descriptor["key"],
                    err,
                )
            if failures >= 5:
                break

    async def _read_with_reconnect(self, address: int, count: int, reason: str):
        try:
            return await self._transport.read(address, count)
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            self._transport.record_failure(err)
            error = str(err).lower()
            if not any(
                token in error for token in ("broken pipe", "connection", "reset")
            ):
                raise
            recreate = "broken pipe" in error or "reset" in error
            if not await self._transport.reconnect(
                reason=reason, recreate_client=recreate
            ):
                if recreate or not await self._transport.reconnect(
                    reason=f"{reason}:retry_recreate", recreate_client=True
                ):
                    return None
            return await self._transport.read(address, count)

    @staticmethod
    def _is_error_response(result: Any) -> bool:
        if hasattr(result, "isError") and callable(result.isError):
            return bool(result.isError())
        if hasattr(result, "is_error") and callable(result.is_error):
            return bool(result.is_error())
        return not hasattr(result, "registers") or result.registers is None

    @staticmethod
    def decode_register(
        registers: list[int], descriptor: dict[str, Any]
    ) -> float | int | str | None:
        dtype = descriptor.get("type")
        scale = descriptor.get("scale", 1)
        if dtype in ("uint16", "int16") and registers:
            raw = registers[0]
            if dtype == "int16" and raw >= 0x8000:
                raw -= 0x10000
        elif dtype in ("uint32", "int32") and len(registers) >= 2:
            raw = (registers[0] << 16) | registers[1]
            if dtype == "int32" and raw >= 0x80000000:
                raw -= 0x100000000
        elif dtype == "ascii" and registers:
            width = descriptor.get("ascii_width", 2)
            chars: list[str] = []
            for register in registers:
                high, low = (register >> 8) & 0xFF, register & 0xFF
                if width == 1:
                    chars.append(
                        chr(high)
                        if 0x20 <= high <= 0x7E and not 0x20 <= low <= 0x7E
                        else chr(low)
                        if 0x20 <= low <= 0x7E
                        else "\x00"
                    )
                else:
                    chars.extend((chr(high), chr(low)))
            return "".join(chars).replace("\x00", "").strip()
        else:
            return None
        multiplier = descriptor.get("energy_wh_multiplier")
        if multiplier is not None:
            return raw * multiplier
        return raw / scale if scale and scale != 1 else raw
