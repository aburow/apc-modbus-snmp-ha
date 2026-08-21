# SPDX-License-Identifier: AGPL-3.0-or-later
"""The single Modbus TCP client owner."""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from collections.abc import Callable

from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException

_LOGGER = logging.getLogger(__name__)


def create_modbus_client(host: str, port: int, timeout: int) -> ModbusTcpClient:
    """Create a client with automatic request retries disabled."""
    return ModbusTcpClient(host=host, port=port, timeout=timeout, retries=0)


class ModbusTransport:
    """Serialize Modbus requests and manage their TCP lifecycle."""

    def __init__(
        self,
        hass,
        client: ModbusTcpClient,
        unit: int,
        host: str,
        port: int,
        timeout: int,
        io_lock: asyncio.Lock,
        log_ctx: str,
        mode: str,
        persist_mode: Callable[[str], None] | None,
        keep_connection_open: Callable[[], bool],
        idle_reconnect_seconds: float,
    ) -> None:
        self.hass = hass
        self.client = client
        self.unit = unit
        self.host = host
        self.port = port
        self.timeout = timeout
        self.io_lock = io_lock
        self.log_ctx = log_ctx
        self.mode = (
            "one_request_per_connection"
            if mode == "one_request_per_connection"
            else "session"
        )
        self._persist_mode = persist_mode
        self._keep_connection_open = keep_connection_open
        self._idle_reconnect_seconds = idle_reconnect_seconds
        self.session_request_succeeded = False
        self.promotion_reason: str | None = None
        self.connect_failures = 0
        self.last_io_monotonic = 0.0
        self.reconnect_count = 0
        self.recreate_count = 0
        self.post_connect_delay = 0.05
        self.min_reconnect_delay = 0.0
        self.last_close_monotonic = 0.0
        self._set_read_signature()

    def _set_read_signature(self) -> None:
        read_params = inspect.signature(self.client.read_holding_registers).parameters
        self._unit_param_candidates = [
            name for name in ("device_id", "slave", "unit") if name in read_params
        ]
        self._resolved_unit_param: str | None = None

    def promote(self, reason: str) -> None:
        """Persist one-request mode after a proven persistent-session failure."""
        if self.mode != "session" or not self.session_request_succeeded:
            return
        self.mode = "one_request_per_connection"
        self.promotion_reason = reason
        if self._persist_mode:
            self._persist_mode(self.mode)
        _LOGGER.warning(
            "[%s] Switched to one Modbus connection per request after the persistent connection failed.",
            self.log_ctx,
        )
        _LOGGER.debug("[%s] Transport promotion reason: %s", self.log_ctx, reason)

    def reconnect_pacing_remaining(self) -> float:
        """Seconds still required before the next TCP connect, if any."""
        if self.min_reconnect_delay <= 0 or self.last_close_monotonic <= 0:
            return 0.0
        return max(
            0.0,
            self.min_reconnect_delay - (time.monotonic() - self.last_close_monotonic),
        )

    async def _await_reconnect_pacing(self) -> None:
        remaining = self.reconnect_pacing_remaining()
        if remaining > 0:
            _LOGGER.debug(
                "[%s] Waiting %.3fs before reconnect (min gap %.1fs since last close)",
                self.log_ctx,
                remaining,
                self.min_reconnect_delay,
            )
            await asyncio.sleep(remaining)

    def _mark_closed(self) -> None:
        self.last_close_monotonic = time.monotonic()

    def mark_io_activity(self) -> None:
        self.last_io_monotonic = time.monotonic()
        if self.mode == "session":
            self.session_request_succeeded = True

    def _read_holding_registers(self, address: int, count: int):
        read_fn = self.client.read_holding_registers
        attempts: list[tuple[str, object]] = []
        if self._resolved_unit_param:
            attempts.append(("kw", self._resolved_unit_param))
        attempts.extend(
            ("kw", candidate)
            for candidate in self._unit_param_candidates
            if candidate != self._resolved_unit_param
        )
        attempts.extend((("positional", self.unit), ("none", None)))
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
        if last_type_error:
            raise last_type_error
        raise TypeError("No compatible pymodbus read_holding_registers signature found")

    def _read_one_request(self, address: int, count: int):
        remaining = self.reconnect_pacing_remaining()
        if remaining > 0:
            _LOGGER.debug(
                "[%s] Waiting %.3fs before reconnect (min gap %.1fs since last close)",
                self.log_ctx,
                remaining,
                self.min_reconnect_delay,
            )
            time.sleep(remaining)
        if not self.client.connect():
            raise ConnectionException("Unable to open Modbus connection")
        try:
            return self._read_holding_registers(address, count)
        finally:
            self.client.close()
            self._mark_closed()

    async def read(self, address: int, count: int):
        """Read one holding-register range through the configured connection mode."""
        request = functools.partial(
            self._read_one_request
            if self.mode == "one_request_per_connection"
            else self._read_holding_registers,
            address,
            count,
        )
        result = await self.hass.async_add_executor_job(request)
        self.mark_io_activity()
        return result

    @staticmethod
    def _write_method_name(words: tuple[int, ...], force_multiple: bool) -> str:
        """Select the one Modbus write function for an already-fixed command."""
        return (
            "write_registers" if force_multiple or len(words) > 1 else "write_register"
        )

    @staticmethod
    def _write_payload(words: tuple[int, ...], force_multiple: bool):
        """Use a register list whenever function 16 is selected."""
        return list(words) if force_multiple or len(words) > 1 else words[0]

    def _write_registers(
        self, address: int, words: tuple[int, ...], force_multiple: bool
    ):
        """Send exactly one function-6 or function-16 request."""
        method_name = self._write_method_name(words, force_multiple)
        write_fn = getattr(self.client, method_name)
        parameters = inspect.signature(write_fn).parameters
        payload = self._write_payload(words, force_multiple)
        options = (
            {"no_response_expected": False}
            if "no_response_expected" in parameters
            else {}
        )
        for unit_name in ("device_id", "slave", "unit"):
            if unit_name in parameters:
                return write_fn(address, payload, **{unit_name: self.unit}, **options)
        return write_fn(address, payload, **options)

    @staticmethod
    def _write_response_valid(response, address: int, words: tuple[int, ...]) -> bool:
        """Require the Modbus acknowledgement to echo the complete request."""
        error = getattr(response, "isError", getattr(response, "is_error", None))
        if response is None or (callable(error) and error()):
            return False
        if getattr(response, "address", None) != address:
            return False
        if len(words) == 1:
            value = getattr(response, "value", None)
            registers = getattr(response, "registers", ())
            return (
                value if value is not None else (registers[0] if registers else None)
            ) == words[0]
        return getattr(response, "count", None) == len(words)

    @staticmethod
    def _write_response_details(response) -> dict[str, object]:
        """Return safe response fields for an experimental command debug record."""
        error = getattr(response, "isError", getattr(response, "is_error", None))
        return {
            "type": type(response).__name__ if response is not None else "None",
            "function": getattr(response, "function_code", None),
            "address": getattr(response, "address", None),
            "count": getattr(response, "count", None),
            "exception": getattr(response, "exception_code", None),
            "error": error() if callable(error) else bool(error),
        }

    async def write(
        self,
        address: int,
        words: tuple[int, ...],
        *,
        command_name: str,
        force_multiple: bool,
    ) -> None:
        """Serialize one command without retrying or reconnecting after it is sent."""
        if not words or getattr(self.client, "retries", 0) not in (None, 0):
            raise ValueError("unsafe_modbus_write")
        async with self.io_lock:
            # Reconnecting before dispatch is safe; never retry after dispatch.
            if not await self.ensure_connection():
                raise ConnectionException("Unable to open Modbus connection")
            if self.mode == "one_request_per_connection":
                response = await self.hass.async_add_executor_job(
                    self._write_one_request, address, words, force_multiple
                )
            else:
                response = await self.hass.async_add_executor_job(
                    self._write_registers, address, words, force_multiple
                )
            details = self._write_response_details(response)
            valid = self._write_response_valid(response, address, words)
            _LOGGER.debug(
                "[%s] Command sent once: action=%s, transport=%s, request_address=0x%04X, "
                "request_count=%d, response_type=%s, response_function=%s, "
                "response_address=%s, response_count=%s, exception_code=%s, valid=%s",
                self.log_ctx,
                command_name,
                self.mode,
                address,
                len(words),
                details["type"],
                details["function"],
                details["address"],
                details["count"],
                details["exception"],
                valid,
            )
            if not valid:
                raise RuntimeError("modbus_write_response_invalid")
            self.mark_io_activity()

    def _write_one_request(
        self, address: int, words: tuple[int, ...], force_multiple: bool
    ):
        """Open once, write once, and close; never replay a command."""
        remaining = self.reconnect_pacing_remaining()
        if remaining > 0:
            time.sleep(remaining)
        if not self.client.connect():
            raise ConnectionException("Unable to open Modbus connection")
        try:
            return self._write_registers(address, words, force_multiple)
        finally:
            self.client.close()
            self._mark_closed()

    async def ensure_connection(self) -> bool:
        if self.mode == "one_request_per_connection":
            return True
        if self._keep_connection_open() and self.last_io_monotonic > 0:
            if (
                time.monotonic() - self.last_io_monotonic
                >= self._idle_reconnect_seconds
            ):
                if await self.reconnect(reason="idle", recreate_client=False):
                    return True
                return await self.reconnect(reason="idle_retry", recreate_client=True)
        try:
            await self._await_reconnect_pacing()
            ok = await self.hass.async_add_executor_job(self.client.connect)
            if ok:
                self.connect_failures = 0
                self.mark_io_activity()
                if self.post_connect_delay > 0:
                    await asyncio.sleep(self.post_connect_delay)
                return True
            self.connect_failures += 1
            if self.connect_failures >= 3:
                self.connect_failures = 0
                return await self.reconnect(
                    reason="connect_failures>=3", recreate_client=True
                )
            return False
        except (ConnectionException, ModbusException, OSError, TimeoutError) as err:
            _LOGGER.debug("[%s] Connection attempt failed: %s", self.log_ctx, err)
            return False

    async def reconnect(self, *, reason: str, recreate_client: bool) -> bool:
        self.reconnect_count += 1
        if recreate_client:
            self.recreate_count += 1
            await self._recreate_client()
        else:
            await self.close()
        await self._await_reconnect_pacing()
        started = time.monotonic()
        ok = await self.hass.async_add_executor_job(self.client.connect)
        _LOGGER.debug(
            "[%s] reconnect(reason=%s, recreate=%s) -> %s (%.3fs, total_reconnects=%d, total_recreates=%d)",
            self.log_ctx,
            reason,
            recreate_client,
            ok,
            time.monotonic() - started,
            self.reconnect_count,
            self.recreate_count,
        )
        if ok:
            self.connect_failures = 0
            self.mark_io_activity()
            if self.post_connect_delay > 0:
                await asyncio.sleep(self.post_connect_delay)
        return ok

    async def close(self) -> None:
        try:
            await self.hass.async_add_executor_job(self.client.close)
        except (ConnectionException, ModbusException, OSError, TimeoutError):
            pass
        finally:
            self._mark_closed()

    async def _recreate_client(self) -> None:
        await self.close()
        self.client = create_modbus_client(self.host, self.port, self.timeout)
        self._set_read_signature()

    def record_failure(self, err: Exception) -> None:
        if not (
            isinstance(err, ModbusException)
            and not isinstance(err, ConnectionException)
        ) and isinstance(err, (OSError, TimeoutError, ConnectionException)):
            self.promote(type(err).__name__)
